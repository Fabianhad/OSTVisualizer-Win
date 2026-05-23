import logging
from pathlib import Path


class LoggerFactory:
    _configured = False

    @classmethod
    def configure(
        cls,
        log_dir: Path,
        level: int = logging.INFO,
        console_level: int = logging.WARNING,
    ):
        if cls._configured:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log")
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        logging.getLogger("wgpu").setLevel(logging.ERROR)
        cls._configured = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        if not cls._configured:
            logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)
