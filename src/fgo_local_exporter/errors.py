"""异常只携带固定代码，不包含原始报文或凭据。"""

__all__ = ["ExportError"]


class ExportError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
