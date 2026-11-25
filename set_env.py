import os
Import("env")

def apply_env_vars():
    try:
        if not os.path.isfile(".env"):
            print("Warning: .env file not found.")
            return

        with open(".env") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    parts = line.strip().split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        # 1. REMOVE OUTER QUOTES 
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        # 2. ESCAPE NEWLINES (Vital for the Cert)
                        value = value.replace(r"\n", r"\\n")
                        # 3. ESCAPE INTERNAL QUOTES
                        value = value.replace(r'"', r'\"')

                        env.Append(CPPDEFINES=[
                            (key, f'\\"{value}\\"')
                        ])

    except Exception as e:
        print(f"Error processing .env: {e}")

apply_env_vars()
if env.subst("$PIOENV").endswith("-managed"):
    from pathlib import Path

    trust_path = Path(os.environ.get("PANEL_TRUST_CONFIG", "")).expanduser().resolve()
    if not trust_path.is_file():
        raise ValueError("Set PANEL_TRUST_CONFIG to the managed service's public trust header")
    env.Append(CPPDEFINES=[("PANEL_TRUST_CONFIG", env.StringifyMacro(trust_path.as_posix()))])
    emergency_path = os.environ.get("PANEL_EMERGENCY_CONFIG")
    if emergency_path:
        issuer_path = Path(emergency_path).expanduser().resolve(strict=True)
        env.Append(CPPDEFINES=[("PANEL_EMERGENCY_CONFIG", env.StringifyMacro(issuer_path.as_posix()))])
    fixed_image_path = os.environ.get("PANEL_FIXED_IMAGE_CONFIG")
    if fixed_image_path:
        fixed_image_header = Path(fixed_image_path).expanduser().resolve(strict=True)
        env.Append(CPPDEFINES=[("PANEL_FIXED_IMAGE_CONFIG", env.StringifyMacro(fixed_image_header.as_posix()))])
