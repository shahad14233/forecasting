# Tender Browser Automation Pipeline

هذا المشروع يطبق **Browser Automation** بطريقة deterministic (باستخدام Playwright) بدل scraping عشوائي.

## التصميم

- **Extractor (Bronze):**
  - تسجيل الدخول بحساب مصرح.
  - فتح صفحة قائمة المنافسات.
  - جمع روابط المنافسات.
  - فتح كل منافسة وقراءة التابات المطلوبة.
  - حفظ HTML الخام + snapshots.
- **Parser/Structured (Silver):**
  - استخراج الحقول عبر labels العربية (مثل: `اسم المنافسة`, `رقم المنافسة`, `تاريخ فتح العروض`).
  - حفظ جدول CSV منظم.
- **Export (Gold):**
  - إخراج جدول reporting جاهز (CSV حالياً).

## الملفات

- `src/tenders_pipeline.py`: بايبلاين الاستخراج والتحويل والإخراج.
- `notebooks/fabric_orchestrator.py`: Orchestrator مناسب للتشغيل المجدول داخل Fabric Notebook.

## التشغيل

```bash
pip install playwright
playwright install chromium

export TENDERS_BASE_URL="https://..."
export TENDERS_COMPETITIONS_URL="https://.../competitions"
export TENDERS_USERNAME="..."
export TENDERS_PASSWORD="..."
export MAX_COMPETITIONS="50"
python src/tenders_pipeline.py
```

## هل الكود قابل للتشغيل داخل Fabric Notebook؟

نعم. فيه طريقتين:

1) **تشغيل مباشر من Notebook** (المفضل):

```python
from notebooks.fabric_orchestrator import run_pipeline
run_pipeline(output_dir="/lakehouse/default/Files/tenders_pipeline", max_competitions=50)
```

2) **تشغيل كسكربت**:

```bash
python src/tenders_pipeline.py --output-dir /lakehouse/default/Files/tenders_pipeline --max-competitions 50
```

> ملاحظة: لازم توفر Runtime المتصفح (Chromium) داخل البيئة.

## Best Practices المطبقة

- استخدام Tender ID كمفتاح أساسي.
- دعم incremental pull (تخطي السجلات الموجودة مسبقًا في Silver).
- فصل extractor عن parser وعن export.
- retry/screenshot عند الفشل لكل صفحة.
- التعامل مع tabs بالنقر وقراءة كل tab على حدة.
- الاعتماد على labels العربية بدل ترتيب العناصر بصرياً.
