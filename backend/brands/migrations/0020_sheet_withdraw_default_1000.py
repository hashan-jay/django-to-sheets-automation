from django.db import migrations, models


def use_withdraw_row_1000(apps, schema_editor):
    GoogleSheetSetting = apps.get_model("brands", "GoogleSheetSetting")
    GoogleSheetSetting.objects.filter(slot__in=(2, 3), withdraw_start_row=1024).update(withdraw_start_row=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0019_google_sheet_auto_sync"),
    ]

    operations = [
        migrations.AlterField(
            model_name="googlesheetsetting",
            name="withdraw_start_row",
            field=models.PositiveIntegerField(default=1000),
        ),
        migrations.RunPython(use_withdraw_row_1000, migrations.RunPython.noop),
    ]
