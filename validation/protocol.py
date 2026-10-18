def receive(connection, size):
    value = bytearray()
    while len(value) < size:
        part = connection.recv(size - len(value))
        if not part:
            raise ConnectionError("incomplete validation message")
        value.extend(part)
    return bytes(value)
