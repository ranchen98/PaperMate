class BusinessException(Exception):
    def __init__(self, code: int = 500, message: str = "服务异常"):
        self.code = code
        self.message = message
        super().__init__(self.message)