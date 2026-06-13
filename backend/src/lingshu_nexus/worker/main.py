"""Worker entrypoint placeholder for future queue tasks."""

from lingshu_nexus.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    print(
        "lingshu-worker ready "
        f"env={settings.app_env} default_domain_id={settings.default_domain_id}"
    )


if __name__ == "__main__":
    main()
