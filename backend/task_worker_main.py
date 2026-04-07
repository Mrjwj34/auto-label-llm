from __future__ import annotations

from backend.services.redis_client import ping_redis
from backend.tasks.job_handlers import TASK_HANDLERS
from backend.tasks.worker import RedisTaskWorker


def main() -> None:
    ping_redis()
    worker = RedisTaskWorker(handlers=TASK_HANDLERS)
    worker.run_forever()


if __name__ == "__main__":
    main()
