from django.db import migrations, models
import django.db.models.deletion


def create_extra_slots(apps, schema_editor):
    GoogleSheetSetting = apps.get_model("brands", "GoogleSheetSetting")
    for slot in (2, 3):
        if GoogleSheetSetting.objects.filter(slot=slot).exists():
            continue
        GoogleSheetSetting.objects.create(id=slot, slot=slot, sheet_url="", blocked=False)
    schema_editor.execute(
        "SELECT setval(pg_get_serial_sequence('brands_googlesheetsetting', 'id'), "
        "(SELECT COALESCE(MAX(id), 1) FROM brands_googlesheetsetting))"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0016_group_ah"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="slot",
            field=models.PositiveSmallIntegerField(default=1, unique=True),
        ),
        migrations.AddField(
            model_name="googlesheetsetting",
            name="blocked",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sheetexport",
            name="slot",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="sheetexport",
            name="transaction",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sheet_exports",
                to="brands.transaction",
            ),
        ),
        migrations.AddConstraint(
            model_name="sheetexport",
            constraint=models.UniqueConstraint(fields=("transaction", "slot"), name="sheet_export_once"),
        ),
        migrations.AlterModelOptions(
            name="googlesheetsetting",
            options={"ordering": ["slot"]},
        ),
        migrations.RunPython(create_extra_slots, migrations.RunPython.noop),
    ]
