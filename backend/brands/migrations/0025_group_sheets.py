from django.db import migrations, models


def mark_kaboom_sheets(apps, schema_editor):
    GoogleSheetSetting = apps.get_model("brands", "GoogleSheetSetting")
    GoogleSheetSetting.objects.filter(group="").update(group="KABOOM77")


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0024_group_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="group",
            field=models.CharField(default="KABOOM77", max_length=64),
        ),
        migrations.AlterField(
            model_name="brand",
            name="group",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="googlesheetsetting",
            name="slot",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="googlesheetsetting",
            constraint=models.UniqueConstraint(fields=("group", "slot"), name="uniq_group_sheet_slot"),
        ),
        migrations.RunPython(mark_kaboom_sheets, migrations.RunPython.noop),
    ]
