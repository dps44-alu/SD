import sys

class DE:
    def __init__(self, port):
        self.port = port


def main():
    if len(sys.argv) < 2:
        print("USAGE: python3 EC_DE.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    taxi = DE(port)


if __name__ == "__main__":
    main()