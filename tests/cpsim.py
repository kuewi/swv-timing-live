"""Simulierter TAG Heuer CP 545 (THCOM08 ueber TCP), Verhalten wie im Test von Stefan."""
import socket, threading, time

class CPSim:
    def __init__(self, scan_port=17000, data_port=23500, readback=True):
        self.clients = []
        self.next = {1: 1, 4: None}
        self.seq = {1: 0, 4: 0}
        self.course = []          # [(nr, tod, seq)] in Startreihenfolge
        self.recs = {}            # (ch, seq) -> [nr, tod]
        self.results = []
        self.readback = readback
        self.received = []
        self.run = 1
        self.lock = threading.Lock()
        self.socks = []
        for port in (scan_port, data_port):
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port)); s.listen(5); self.socks.append(s)
            threading.Thread(target=self.accept, args=(s, port == data_port), daemon=True).start()
        self.t0 = time.time()

    def tod(self):
        lt = time.localtime(); return lt.tm_hour*3600+lt.tm_min*60+lt.tm_sec+(time.time()%1)

    @staticmethod
    def ts(tod):
        h, r = divmod(tod, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{s:08.5f}"

    def accept(self, s, data):
        while True:
            try: c, _ = s.accept()
            except OSError: return
            if data: self.clients.append(c)
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def send(self, line, c=None):
        for cl in ([c] if c else list(self.clients)):
            try: cl.sendall((line + "\r\n").encode())
            except OSError: pass

    def serve(self, c):
        buf = b""
        while True:
            try: d = c.recv(1024)
            except OSError: break
            if not d: break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.cmd(line.decode().strip(), c)
        if c in self.clients: self.clients.remove(c)

    def cmd(self, t, c):
        self.received.append(t)
        p = t.split()
        if t == "#SN": self.send("SN 04711 CP545 VB12", c); self.send("AK C", c); return
        if t == "#!T": self.send("!T " + self.ts(self.tod())[:8] + " 20/11/26", c); self.send("AK C", c); return
        if p[:2] == ["#RP", "001"]: self.send("&P 001 2", c); self.send("AK C", c); return
        if p[:2] == ["#RP", "003"]: self.send(f"&P 003 {self.run:02d} {self.run+1:02d} 11:00:00 09820", c); self.send("AK C", c); return
        if p[:2] == ["#RP", "026"]:
            ch = int(p[2]); v = self.next.get(ch) or 0
            if self.readback: self.send(f"&P 026 {ch:02d} {v:04d}", c)
            self.send("AK C", c); return
        if p[:2] == ["#WP", "026"]:
            ch = int(p[2]); self.next[ch] = int(p[3]); self.send("AK C", c); return
        if p[:2] == ["#WC", "013"]:
            ch, seq = int(p[2]), int(p[3]); new = t[len("#WC 013 01 0000 "):]
            r = self.recs.get((ch, seq))
            if not r: self.send("AK F", c); return
            self.send("AK C", c)
            if new.strip() == "C":
                self.send(f"TC {r[0]:4d} {seq:4d} M{ch} {self.ts(r[1])}  9820"); r[0] = 0
                self.course = [x for x in self.course if x[2] != seq or ch != 1]
            else:
                n = int(new)
                self.send(f"T- {r[0]:4d} {seq:4d} M{ch} {self.ts(r[1])}  9820")
                old = r[0]; r[0] = n
                self.send(f"T* {n:4d} {seq:4d} M{ch} {self.ts(r[1])}  9820")
                if ch == 1:
                    self.course = [(n if x[2] == seq else x[0], x[1], x[2]) for x in self.course]
                if ch == 4:  # Umbuchung Ziel: alter Fahrer wieder auf der Strecke, neuer weg
                    st = next(x for x in self.all_starts if x[0] == old)
                    self.course = [x for x in self.course if x[0] != n] + [st]
                    self.course.sort(key=lambda x: x[1])
            return
        self.send("AK R", c)

    def start(self):
        with self.lock:
            nr = self.next[1]; self.next[1] = nr + 1
            self.seq[1] += 1; tod = self.tod()
            self.recs[(1, self.seq[1])] = [nr, tod]
            self.course.append((nr, tod, self.seq[1]))
            self.all_starts = getattr(self, "all_starts", []) + [(nr, tod, self.seq[1])]
            self.send(f"TN {nr:4d} {self.seq[1]:4d} M1 {self.ts(tod)}  9820")
            return nr

    def finish(self):
        with self.lock:
            if not self.course: return None
            nr = self.next[4] if self.next[4] and any(x[0] == self.next[4] for x in self.course) else self.course[0][0]
            self.next[4] = None
            st = next(x for x in self.course if x[0] == nr)
            self.course.remove(st)
            self.seq[4] += 1; tod = self.tod()
            self.recs[(4, self.seq[4])] = [nr, tod]
            self.send(f"TN {nr:4d} {self.seq[4]:4d} M4 {self.ts(tod)}  9820")
            secs = int((tod - st[1]) * 10) / 10
            self.results.append((nr, secs))
            rank = 1 + sum(1 for n, s in self.results if s < secs)
            m, sec = divmod(secs, 60)
            ts = f"{int(m)}:{sec:08.5f}" if m else f"{sec:.5f}"
            self.send(f"RR {rank:4d} {nr:4d}        {ts}")
            return nr, secs

    def drop_clients(self):
        for c in list(self.clients):
            try: c.shutdown(socket.SHUT_RDWR); c.close()
            except OSError: pass
        self.clients.clear()

    def close(self):
        self.drop_clients()
        for s in self.socks: s.close()
