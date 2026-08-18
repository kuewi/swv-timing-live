import serial
import serial.tools.list_ports
import time

COM_PORT = 'COM8'
BAUDRATE = 9600

print(f"Starte Rohdaten-Analyse auf {COM_PORT}...")

try:
    ser = serial.Serial(COM_PORT, baudrate=BAUDRATE, timeout=1.0)
    print(f"Verbunden mit {COM_PORT}. Bitte löse jetzt 2-3 Zeiten am CP 545 aus.")
    print("Drücke STRG+C zum Beenden.\n")
    print("-" * 50)

    while True:
        if ser.in_waiting > 0:
            # Liest alle verfügbaren Bytes direkt aus dem Puffer
            raw_bytes = ser.read(ser.in_waiting)
            
            # 1. Darstellung als Hex-Werte (zeigt Steuerzeichen wie 0x0D, 0x0A, 0x03)
            hex_representation = " ".join([f"{b:02X}" for b in raw_bytes])
            
            # 2. Darstellung als ASCII-Text (Sonderzeichen maskiert)
            ascii_representation = repr(raw_bytes)

            print(f"[HEX]   : {hex_representation}")
            print(f"[ASCII] : {ascii_representation}")
            print("-" * 50)
        
        time.sleep(0.1)

except serial.SerialException as e:
    print(f"Fehler beim Öffnen von {COM_PORT}: {e}")
except KeyboardInterrupt:
    print("\nAnalyse beendet.")
finally:
    if 'ser' in locals() and ser.is_open:
        ser.close()