from django.core.management.base import BaseCommand, CommandError

from apps.itsm.services.flowable import FlowableClient, FlowableConfigurationError, FlowableUnavailable
from apps.itsm.services.verification import FlowableVerificationError, verify_flowable_runtime


class Command(BaseCommand):
    help = "用官方 REST API 验证 ITSM BPMN 的串行、并行、前后加签与处理节点"

    def handle(self, *args, **options):
        try:
            client = FlowableClient(timeout=20.0)
        except FlowableConfigurationError as error:
            raise CommandError(str(error)) from error
        try:
            result = verify_flowable_runtime(client)
        except (FlowableUnavailable, FlowableVerificationError) as error:
            raise CommandError(str(error)) from error
        finally:
            client.close()
        self.stdout.write(
            self.style.SUCCESS("Flowable 验证通过：" f"process_instance_id={result['process_instance_id']} " f"scenarios={','.join(result['scenarios'])}")
        )
