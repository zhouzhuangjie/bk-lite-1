import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("itsm", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="command",
            name="command_type",
            field=models.CharField(
                choices=[
                    ("DEPLOY_VERSION", "发布服务版本"),
                    ("START_TICKET", "启动工单"),
                    ("COMPLETE_TASK", "完成人工任务"),
                    ("PLAN_AFTER_SIGN", "保存后加签计划"),
                    ("RECONCILE_TICKET", "核对工单状态"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="SignPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("task_logical_key", models.CharField(max_length=128)),
                ("user_ids", models.JSONField(default=list)),
                ("created_by_user_id", models.PositiveBigIntegerField()),
                ("created_by_username", models.CharField(max_length=150)),
                ("created_by_domain", models.CharField(max_length=100)),
                ("reason", models.CharField(max_length=500)),
                ("applied", models.BooleanField(db_index=True, default=False)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sign_plans", to="itsm.ticket")),
            ],
            options={
                "db_table": "itsm_sign_plan",
            },
        ),
        migrations.AddConstraint(
            model_name="signplan",
            constraint=models.UniqueConstraint(fields=("ticket", "task_logical_key"), name="uq_itsm_sign_plan_task"),
        ),
    ]
