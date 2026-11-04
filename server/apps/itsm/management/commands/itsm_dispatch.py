from __future__ import annotations

import signal
import threading
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.core.logger import itsm_logger as logger
from apps.itsm.services.dispatcher import MAX_BATCH_SIZE, dispatch_command, due_command_ids
from apps.itsm.services.flowable import FlowableClient, FlowableConfigurationError

MIN_INTERVAL_SECONDS = 0.2
MAX_INTERVAL_SECONDS = 10.0


class Command(BaseCommand):
    help = "运行 ITSM Flowable 命令分发器（独立进程，不占用 Celery）"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="处理一批到期命令后退出")
        parser.add_argument("--interval", type=float, default=1.0, help="空闲轮询间隔，范围 0.2 到 10 秒")
        parser.add_argument("--batch-size", type=int, default=20, help=f"单批命令数，范围 1 到 {MAX_BATCH_SIZE}")

    def handle(self, *args, **options):
        interval = float(options["interval"])
        batch_size = int(options["batch_size"])
        if not MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
            raise CommandError("--interval 必须在 0.2 到 10 秒之间")
        if not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise CommandError(f"--batch-size 必须在 1 到 {MAX_BATCH_SIZE} 之间")

        stopped = threading.Event()

        def request_stop(signum, frame):
            stopped.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        try:
            client = FlowableClient()
        except FlowableConfigurationError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS("ITSM 命令分发器已启动"))
        try:
            while not stopped.is_set():
                close_old_connections()
                command_ids = due_command_ids(batch_size=batch_size)
                for command_id in command_ids:
                    if stopped.is_set():
                        break
                    dispatch_command(command_id, client=client)
                close_old_connections()
                if options["once"]:
                    return
                if not command_ids:
                    stopped.wait(interval)
                else:
                    time.sleep(0)
        finally:
            client.close()
            close_old_connections()
            logger.info("event=itsm_dispatcher_stopped")
