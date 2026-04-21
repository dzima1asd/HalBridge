from __future__ import annotations


def device_command(text: str, bridge) -> str | None:
    """
    Cienka delegacja do warstwy sprzętowej.
    Zwraca wynik tekstowy lub None, jeśli nie rozpoznano.
    """
    try:
        result = bridge.execute(text)
        if result:
            print(f"[HARDWARE] {result}")
        return result
    except Exception as e:
        print(f"[hardware_bridge error] {e}")
        return None
