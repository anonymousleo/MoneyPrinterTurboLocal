
from __future__ import annotations
import importlib.metadata

def main():
    import perth
    perth_version = importlib.metadata.version("resemble-perth")
    setuptools_version = importlib.metadata.version("setuptools")
    watermarker = getattr(perth, "PerthImplicitWatermarker", None)
    print(f"RESEMBLE_PERTH={perth_version}")
    print(f"SETUPTOOLS={setuptools_version}")
    print(f"PERTH_WATERMARKER_CALLABLE={callable(watermarker)}")
    if not callable(watermarker):
        raise SystemExit("PERTH_RUNTIME_FAIL")
    obj = watermarker()
    print(f"PERTH_CONSTRUCTOR_PASS={type(obj).__name__}")
    print("CHATTERBOX_PERTH_RUNTIME_PASS")

if __name__ == "__main__":
    main()
