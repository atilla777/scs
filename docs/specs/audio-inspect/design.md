# Полный кандидат `audio-inspect-design-v1`

## 1. Область, входы и статус

- Область: самостоятельная операция `audio inspect`, FR-06, epic `scs-vfl`; ID фичи отсутствует.
- Это первоначальный **предлагаемый дизайн**, не принятый документ и не разрешение реализации.
- Вход: полный `docs/specs/audio-inspect/spec.md`, версия `audio-inspect-requirements-v2`.
- SHA-256 входа: `de75b987a4370af4b1ab763311697c6017e56ca1a4702dceedf5ffcde0ac7132`.
- Отдельное принятие: `docs/specs/audio-inspect/decisions.md`, раздел «Принятие требований audio-inspect-requirements-v2».
- Оба файла прочитаны полностью; исторические слова «кандидат/несохранённый» не отменяют отдельного принятия.
- Рабочая копия: `/tmp/opencode/scs-audio-inspect-preparation`, ветка `prepare/audio-inspect`.
- Проверенный HEAD/base: `6d583820b0af05f440df9ed7a0ee16827aed7d1d`.
- Основная копия: `/home/aleksei/plums/scs`; принадлежность подтверждена общим Git directory `/home/aleksei/plums/scs/.git`.
- Конфигурация выбранной копии: `ris.yaml`, корректная v2; `sources.rules/product/specs` разрешаются относительно неё.
- Нормы: фактически прочитанные `architecture-init-v2`, `engineering-process-v2`, а не прежняя инженерная версия.
- Shared workspace и execution-роли для этой read-only операции не требуются; установленный реестр skills остаётся в основной копии.

## 2. Наблюдаемая база и совместимость

- Runtime расположен в `skills/supercollider/scripts/scs_tool/`; вход — `scripts/sc-tool.py`.
- `cli.py:main` сейчас импортирует `render.execute` до выбора операции и владеет сигналами/JSON-транспортом.
- `render.execute` загружает SC/process-адаптеры, применяет собственные platform/dependency gates и возвращает schema 2.
- `wav.read_wav` измеряет PCM16 для render; `FloatInput.blocks` намеренно отвергает nonfinite Buffer-ресурсы.
- Эти readers не подходят inspect без изменения политики: смешивать разрешённые диагностические nonfinite с ресурсами render нельзя.
- Существующие seams: stdlib `unittest`, `tests/unit`, subprocess-контракты в `tests/contract`, opt-in native headless integration.
- Соседний `nrt-render-design-v2` и его отдельное принятие просмотрены; текущий код важнее исторического утверждения дизайна «реализации нет».
- Не меняются `scs-nrt-source/2`, render JSON schema 2, критерии готовности render, ресурсные snapshots и отказ nonfinite ресурсов.
- Не проектируются validate, plot, воспроизведение, конверсия или будущие аудиооперации.

## 3. Стек и границы компонентов

- Повторно используются CPython **3.14.7**, stdlib, существующий переносимый source-package layout и PEP 8.
- Первоначальный профиль inspect: Linux x86_64, CPython 3.14.7, обычная локальная POSIX FS.
- Это выбранный профиль будущей проверки, не утверждение, что новый inspect уже проверен.
- SC, libsndfile, hard links, procfs/pidfd, libc process gates, GUI и аудиоустройства inspect не нужны.
- Новых Python-зависимостей, lock-файла, build backend, форматтера, установки или CI не вводится.
- `cli.py` выбирает операцию **до импорта** соответствующего coordinator; неизвестные операции сохраняют прежний render fallback.
- Для `audio inspect` импортируется только новый `scs_tool/audio_inspect.py`; `.render/.sc/.processes/.files` не импортируются.
- `audio_inspect.py` владеет запросом, состоянием операции, descriptor, reader, accumulator, полнотой и диагностическим решением.
- Новый `scs_tool/inspect_wav.py` отвечает за ограниченное чтение RIFF и декодирование, не за критерий успешности.
- Чистый accumulator получает complete frames и эффективные параметры; не открывает файлы и не знает CLI/SC/RIS.
- Направление зависимостей: CLI → inspect coordinator → reader/чистые измерения; обратных обращений нет.
- Старый `wav.py` в этой фиче не обобщается: небольшое дублирование RIFF-проверок безопаснее изменения принятого render verifier.

## 4. Публичный CLI

```text
python3 -B <skill-root>/scripts/sc-tool.py audio inspect
  --input PATH
  [--silence-threshold-dbfs DECIMAL]
  [--min-silence-duration SECONDS]
  [--max-intervals INTEGER]
  [--timeout SECONDS]
  [--json]
```

- Обязателен ровно один `--input`; positional path, stdin `-`, неизвестные и повторные ключи отвергаются.
- Defaults: threshold `-60`, min duration `0.1`, max intervals **10000**, timeout **0** — отключён.
- `--json` явно выбирает уже установленный default; text/output/diagnostics-dir flags отсутствуют.
- Threshold — конечное десятичное число `T≤0`; duration — конечное десятичное `D≥0`.
- Timeout — конечное десятичное `0…86400` секунд; положительное значение задаёт отдельную остановку по deadline.
- Max intervals — целое `0…100000`; ноль разрешает обследование без хранения интервалов.
- Decimal syntax: знак, десятичная точка, необязательный exponent; NaN/Inf, underscores и locale-запятая недопустимы.
- T/D сохраняются как точные десятичные значения, не предварительно округлённые binary64; возвращаются строками.
- Большая или малая конечная величина T/D сама по себе не является неверным параметром.
- Относительный input разрешается от исходного cwd; нет shell expansion, `~`, интерполяции или исполнения.
- Неверные параметры диагностируются до открытия/анализа аудио; ошибки транспорта не маскируются под ошибки файла.

## 5. Файл, идентичность и сроки жизни

- Coordinator открывает input read-only; descriptor принадлежит только этому вызову и закрывается на любом исходе.
- До чтения проверяются компоненты пути: symlink-компоненты отвергаются; basename также открывается с `O_NOFOLLOW`.
- Для обхода каталогов используются directory descriptors; input — `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`.
- `fstat` подтверждает regular file; FIFO/устройства не читаются и не могут заблокировать операцию на открытии.
- Снимок стабильности: `dev, ino, mode, size, mtime_ns, ctime_ns`; atime намеренно исключён.
- После чтения сравниваются descriptor snapshot и доступная identity по исходному пути; исчезновение/замена означает неподтверждённость.
- Проверка ловит наблюдаемые изменения, но не доказывает отсутствие всех concurrent rewrites, ABA или злонамеренных rename всей иерархии.
- Нет копирования входа, hashes как замены стабильности, locks, repair, временных каталогов или долговременных audit-файлов.
- Содержимое/mtime не изменяются инструментом; обычное filesystem-обновление atime от чтения возможно.
- Сигнальные handlers принадлежат CLI, только latch SIGINT/SIGTERM; прежние handlers восстанавливаются.
- Inspect не меняет umask и не запускает ProcessOwner; прежний render transport сохраняет свой режим.

## 6. RIFF/WAVE reader

- Проверяются сигнатуры, `riff_size+8==initial_stat_size`, полное потребление контейнера и физический EOF.
- RF64/RIFX/другой контейнер дают `unsupported_format`, не попытку конверсии.
- Chunk length — little-endian uint32; перед чтением проверяются header, payload end и обязательный pad byte нечётной длины.
- Pad byte обязан существовать, но не обязан быть нулевым; ancillary chunks допускаются до/между/после fmt/data.
- Требуются ровно один `fmt ` и один `data`, причём fmt раньше data; дубликат после audio также запрещает успех.
- Неизвестные chunks читаются и отбрасываются порциями, не загружаются целиком и не пропускаются как доказанно прочитанные.
- Fmt читается фиксированным необходимым префиксом; остаток bounded-streamed, размер из header не определяет allocation.
- PCM tag 1: signed little-endian 16 bits; IEEE tag 3: little-endian binary32.
- Extensible tag 65534: minimum 40 bytes, `cbSize≥22`, объявленное расширение помещается в fmt.
- Допустимы стандартные PCM/IEEE GUID; container bits/valid bits соответственно **16/16** либо **32/32**.
- Неподдерживаемые subtype/bit depth — `unsupported_format`; нарушенная структура расширения — `audio_corrupt`.
- Для non-extensible fmt: длина 16 допустима; при наличии extension требуется поле cbSize и согласованная длина.
- Rate/channels положительны; `block_align==channels*bytes_per_sample`, `byte_rate==rate*block_align` без integer wrap.
- Channel mask сохраняется как metadata, не меняет порядок каналов; ненулевой mask должен согласовываться с channels.
- Ограничения render `8000…192000/1…32` не применяются; пределы следуют из uint16 align/uint32 rate и согласованного byte rate.
- Data size должен быть кратен align; decode только complete frames, interleaved в файловом порядке.
- Читаются chunks до конца RIFF, включая хвост после data; успех невозможен по одному header или полному audio payload.
- Structural failure прекращает небезопасный разбор; доступные измерения префикса сохраняются с ограничением области.

## 7. Ограниченная обработка и численная модель

- I/O buffer — 65536 bytes; frame может быть больше buffer, поэтому assembler держит не более одного дополнительного frame.
- Максимальный frame ограничен WAV uint16 align; нет массива `frames×channels`, списка chunks или всех samples.
- Header-derived state выделяется только после проверки fmt; его размер O(channels), channels ограничены представлением WAV.
- PCM16 преобразуется точно как `signed/32768`; binary32 точно расширяется в Python binary64, включая subnormal и ±0.
- Перед abs/max выполняется классификация finite/NaN/+Inf/−Inf; NaN не может отравить accumulator.
- Peaks — max abs по конечным samples; общий peak — max канальных, без clamp или downmix.
- Для peak>0 dBFS вычисляется `20*math.log10(peak)`; допустим tolerance численной выдачи, не классификации тишины.
- Для peak=0: `{"linear":0.0,"dbfs":null,"dbfs_kind":"negative_infinity"}`.
- При отсутствии конечных samples peak целиком `null`; это не нулевой peak и не отрицательная бесконечность.
- Минимальный binary32 subnormal и максимальный finite дают конечные binary64 linear/dBFS; overflow квадрата отсутствует.
- Frame indices/counts — точные Python integers; секунды — binary64 `frame/rate`, индексы являются точным oracle.
- Из RIFF uint32 bounds и rate≥1 следует duration<2^32 секунд; переполнение JSON-seconds невозможно.
- Одинаковая модель применяется к границам интервалов и первым nonfinite-позициям.

## 8. Точный порог и длительность

- Нельзя классифицировать через незащищённое `float(10**(T/20))`: underflow и округление меняют R-05.
- Все поддерживаемые finite amplitudes лежат на binary32-сетке; PCM16 — её подмножество.
- До анализа вычисляется максимальная binary32 amplitude, удовлетворяющая точному `x≤10^(T/20)`.
- Применяется binary search по упорядоченным неотрицательным finite bit patterns до 1; затем sample сравнивается с найденной границей.
- ±0 всегда тихие; при T=0 граница ровно 1; amplitudes>1 при T≤0 всегда нетихие.
- Для T≤−1000 положительных тихих samples нет: порог строго ниже минимального binary32 subnormal.
- На оставшемся диапазоне применяется Decimal interval arithmetic с повышением precision, а не фиксированный epsilon.
- `ln(10)` и `exp` получают охватывающие bounds из correctly-rounded Decimal-результатов ±одна ulp; промежуточные операции округляются наружу.
- Граница считается доказанной лишь когда интервалы отделяют соседние binary32 значения; неоднозначность требует большей precision.
- Равенство для положительного dyadic x≤1 и конечного десятичного T возможно здесь только x=1,T=0; этот случай обработан отдельно.
- Precision workspace растёт по необходимости, с checkpoints; MemoryError/арифметический сбой — явный wrapper/resource failure, не приблизительный ответ.
- Эффективная граница возвращается дополнительно как `silence_threshold_linear_f32`, исходный T остаётся нормативным параметром.
- `M=max(1,ceil(D*rate))` считается точно по Decimal coefficient/exponent, без default context rounding.
- Перед расширением больших powers of ten D сравнивается с предельной длительностью RIFF; если M>N_declared, достаточно sentinel `exceeds_declared_frames:true`.
- В таком случае численный `min_silence_frames` — null, а не неточный/переполненный integer; ни одна серия не проходит.
- Для огромного отрицательного exponent D>0, когда D*rate<1, M=1; D=0 также M=1.

## 9. Интервалы, счётчики и усечение

- Для каждого канала и all-channels ведётся start текущей тихой серии; all-channels обновляется из исходных frame predicates.
- Nonfinite разрывает соответствующую канальную серию и all-channels серию, но не другие каналы.
- Серия закрывается при первом нетихом frame; `[start,current_frame)` принимается только при длине≥M.
- На подтверждённом конце data закрываются оставшиеся серии; начало/конец файла не объединяются.
- При остановке внутри data открытая серия не выдаётся завершённой; сохраняются только уже подтверждённые интервалы.
- Глобальный L охватывает **суммарно канальные и all-channels интервалы**, не L на каждый канал.
- Порядок кандидатов: возрастание end_frame, при равном конце каналы 0…C−1, затем all-channels.
- Хранятся первые L кандидатов; сохранённые списки каждого канала имеют возрастающие границы.
- Считаются `total_detected/returned/omitted` глобально и по каждому scope; omitted=detected−returned.
- Точное превышение — detected>L, не detected==L; L=0 и отсутствие интервалов не означает усечения.
- После превышения продолжаются decode, peaks, nonfinite counters, первые позиции и counts интервалов до EOF.
- Детектор не хранит отброшенные интервалы; память O(channels+L), время O(samples+chunks).
- На частичном scan detected относится только к завершённым сериям обследованного префикса; `counts_complete:false`.
- По каналам выдаются finite count, NaN/+Inf/−Inf counts и первая позиция каждого вида либо null.

## 10. JSON-контракт inspect

- Новый независимый контракт: `schema:"scs-audio-inspect"`, `schema_version:1`, `operation:"audio.inspect"`.
- Это **не schema 3 render** и не обещание общей одинаковой структуры всех операций.
- Top-level: `schema, schema_version, operation, status, stage, exit_code, input, requested, effective, measured, completeness, environment, warnings, errors`.
- Status: `success|error|timeout|cancelled`; stage: `input|environment|header|scan|finalize|complete`.
- Input содержит переданный/абсолютный path, initial identity и `stability:"unchanged_observed|changed|unknown"`.
- Requested содержит исходные значения; effective — точные T/D strings, L, timeout, M/sentinel и эффективную binary32 границу.
- Measured содержит container/sample_format/rate/channels, declared_frames, decoded_frames, duration_seconds, channel results, overall peak и all-channels silence.
- Channel result: index, finite_samples, nonfinite counters/first positions, peak, silence intervals и interval counts.
- Interval: `start_frame,end_frame,start_seconds,end_seconds`; sample format: `pcm16|float32`.
- Completeness: `scan_complete, report_complete, measurements_defined, counts_complete, bytes_read, observed_frames, stop_reason`.
- Scan complete означает полное успешное чтение и проверку контейнера, не только data; input instability дополнительно запрещает success.
- Report complete означает полное обследование и отсутствие отброшенных интервалов; nonfinite отдельно делает measurements_defined=false.
- Peaks дополнены `basis:"finite_samples"`; при partial scan их область — decoded prefix, при nonfinite — только finite subset.
- Null означает неизвестное/отсутствующее, не ноль; непрочитанные metadata/measured — null, известные нулевые counts — 0.
- JSON — одна компактная строка, `allow_nan=False`; все float-поля конечны, причины null выражены соседними kind/completeness полями.
- Diagnostic: `{code,stage,message,details}`; фиксированный набор агрегированных причин без per-sample/error-list роста.
- Большой результат сериализуется `JSONEncoder.iterencode`, без второго полного JSON-string allocation.
- Обычные результаты не пишут stderr; при недоступном stdout допустим только аварийный stderr и code 20 без обещания доставленного JSON.

## 11. Отказы, остановки и успех

- Exit 0/success: полная структура/чтение, стабильность unchanged_observed, finite measurements, полный interval report, успешная финализация.
- Exit 2: invalid_input, включая неверные параметры и запрещённый тип/путь input.
- Exit 3: unsupported_environment; проверяются только Linux/x86_64/CPython profile inspect.
- Exit 12: unsupported_format или audio_corrupt — различные diagnostic codes.
- Exit 14: input_unavailable/read_error/input_changed; файл после изменения не объявляется достоверно обследованным оригиналом.
- Exit 15: nonfinite_samples; exit 21: interval_limit; exit 20: wrapper/resource-allocation/transport failure.
- Exit 24/status timeout; exit 130/143/status cancelled для SIGINT/SIGTERM.
- Deadline охватывает parse/threshold/open/read/finalize; default выключен, чтобы не вводить скрытого лимита полного обследования.
- Checkpoints — перед I/O, между blocks, не реже 4096 samples и внутри адаптивных численных расчётов.
- Kernel-hung regular-file I/O, SIGKILL и авария ОС не входят в гарантию своевременного JSON.
- Nonfinite и interval_limit — накопленные результаты, а не причины ранней остановки.
- Если позднее появляется read/corruption/timeout/cancel, именно остановившая причина задаёт code; ранее накопленные причины остаются в errors.
- При полном scan приоритет: input_changed → nonfinite_samples → interval_limit → success; все факты сохраняются.
- Доступные descriptors закрываются в finally; ошибка close запрещает success и сохраняет предыдущие причины.
- Автоматического повтора нет; обнаруженные +2/−2, тишина или пустой корректный WAV сами по себе не ошибка.

## 12. Test seams и покрытие AC

| AC | Проверка и наблюдаемый oracle |
|---|---|
| 001–002 | Малые byte-built PCM16/float32/extensible fixtures; metadata, ancillary до/после data; отклонение RF64/RIFX/PCM24/float64/compressed. |
| 003–004 | Точные −32768/+32767, ±2 и противофаза; linear peak exact, dBFS tolerance 1e−10 dB, никакого downmix. |
| 005–006 | Default/explicit CLI; T=0 и соседние binary32 у 1, T около subnormal cutoff, −1000/очень большие exponent; invalid params до open. |
| 007–008 | Табличные series до/на/после M, Decimal `0.0000625*48000=3`, D=0/огромное/микроскопическое; независимый простой reference detector. |
| 009–010 | Различные NaN bit patterns, ±Inf в каждом канале и последнем frame; точные counts/first positions, разрывы, finite-only/null peaks. |
| 011 | Отдельные mutations RIFF/fmt/cbSize/GUID/align/rate/padding/duplicates/data alignment, включая дефект после полностью прочитанного data. |
| 012 | Injected short reads/OSError/clock/checkpoint; реальный subprocess SIGINT/SIGTERM с pipe-синхронизацией; только complete frames, без закрытия оборванной серии. |
| 013–014 | Нулевой data и непустые ±0; строгий JSON parser, null/kind/status/exit согласованы для успеха и каждого существенного отказа. |
| 015 | L=0/1/default, detected=L/L+1, одновременные закрытия; nonfinite и новый peak после лимита; точные counts и deterministic kept prefix. |
| 016 | Relative/absolute, Unicode/quotes/newline/metacharacters, symlink-компоненты/FIFO/device, замена/изменение input; sentinel files и чужие процессы неизменны. |
| 017 | Public CLI в имеющемся изолированном Linux runner без сети/GUI/audio/SC; импорт render/sc/processes запрещён отдельным import-hook contract. |
| 018 | Неизменённые unit/contract render suites, schema2 snapshots и FloatInput nonfinite rejection; применимый существующий native render regression. |

## 13. Дополнительные проверки и ограничения свидетельств

- Численный seam проверяет outward bounds, удвоение precision, соседние float32 bit patterns и отсутствие underflow-as-zero ошибки.
- Оракулы threshold не должны повторять production exp: отдельные high-precision bounds и аналитические случаи ±0/1/subnormal/PCM16.
- Bound allocations проверяются reader spy: максимальный read size, отсутствие whole-file read, fixed fmt prefix и bounded interval storage.
- Chunk-boundary invariance: одни samples с разным разбиением чтений дают одинаковый результат и порядок.
- Малые fixtures генерируются оригинальным stdlib-кодом проекта под его MIT; origin/назначение/oracle описываются рядом.
- Команды будущей проверки: существующие `python3 -B -m unittest discover -s tests/unit -v` и аналогично `tests/contract`.
- Native integration использует только уже доступный и предварительно подтверждённый runner; отсутствие runner означает blocked/unverified, не pass.
- Новые live-agent/AI, платные, длительные нагрузочные проверки и системная настройка этим дизайном не назначаются.
- На этой read-only стадии тесты, численные эксперименты и native executions **не выполнялись**.

## 14. Альтернативы, документация и решения

- `wave` недостаточен для общего float32; libsndfile/FFmpeg добавили бы зависимости и потенциальную конверсию — выбран собственный узкий reader.
- Общий reader с render сократил бы код, но расширил риск политики nonfinite и совместимости; отложен без изменения публичных требований.
- Float threshold с epsilon проще, но противоречит точной границе; выбран заранее доказанный binary32 cutoff, не дорогая Decimal-операция на каждый sample.
- Per-channel interval quota сложнее и скрывает общий memory bound; выбран единый лимит с явным порядком и counts.
- Обязательный timeout способен остановить корректное большое обследование; выбран выключенный default и явная отдельная остановка.
- Обновляются только относящиеся к inspect SKILL routing, README status, compatibility profile и новая `references/audio-inspect.md`.
- Документация явно отделяет «объективно измерено» от validate; render-зависимости не объявляются предпосылкой inspect.
- Труднообратимые решения: CLI names/defaults, независимая schema identity, null/−∞ модель, global quota ordering и точные decimal semantics.
- Их должен охватывать отдельный акт принятия полного дизайна и независимое ревью; обязательный отдельный ADR нормами не установлен.
- Выявленных противоречий принятым R-01–R-13 нет; изменения этих требований, отказ от точности или ранний stop из-за interval limit требуют нового принятия требований.
- Дополнительный произвольный cap каналов, rate, величины T/D или precision нельзя незаметно внести как «оптимизацию»; при необходимости решение возвращается владельцу требований.
- Реализация остаётся зависимой от отдельного принятия дизайна и положенных проектных проверок; этот кандидат не является готовностью фичи.

**Конец полного кандидата `audio-inspect-design-v1`.**
