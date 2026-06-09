"""Hello World workflow module."""


def hello(name: str = "World") -> str:
    """Return a greeting message.
    
    Args:
        name: Name to greet. Defaults to "World".
        
    Returns:
        Greeting string.
    """
    return f"Hello, {name}!"


def main() -> None:
    """CLI entrypoint for hello world."""
    print(hello())


if __name__ == "__main__":
    main()
