from skypixel.settings import load_env_file


def run() -> None:
    """Load .env, then start the bot."""
    load_env_file()
    # Import after loading .env so import-time settings see its values.
    from skypixel.app import main

    main()


if __name__ == "__main__":
    run()
