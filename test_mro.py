class ImportExportModelAdmin: pass
class ModelAdmin: pass
class BaseAdmin(ModelAdmin): pass
class TestAdmin(BaseAdmin, ImportExportModelAdmin): pass
print(TestAdmin.__mro__)
