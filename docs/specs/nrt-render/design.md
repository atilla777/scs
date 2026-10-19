# Полный кандидат `nrt-render-design-v2`

## 1. Область, основания и статус

Первая NRT-фича epic `scs-vfl`. Feature ID отсутствует; `nrt-render` остаётся предложенным slug.

Основания:

- принятые `nrt-render-requirements-v1`, R-01–R-13, AC-001–018;
- `spec.md`, SHA-256 `71876587af1605c94a57cfadf56e1da4733f64041c961c45da814ccda8123c89`;
- отдельное принятие требований: `decisions.md:3–17`;
- продукт `PF-reuse-2026-10-19-v1`;
- архитектура `architecture-init-v2`;
- инженерные правила `engineering-init-v1`.

Baseline: `/tmp/opencode/scs-nrt-render-preparation`, ветка `prepare/nrt-render`, база `321a084d9fdc29d6d48a349a2116dff541e208e0`, common Git `/home/aleksei/plums/scs/.git`, primary `/home/aleksei/plums/scs`.

Принятый локальный предшественник — `nrt-render-design-v1`, SHA-256 `9134e227e99cb1e9d8b7c99406b15c621769408d0f3bbdba4a46e4758b7d15bf`; его историческое принятие сохраняется. Оно не распространяется на v2.

Реализованного продуктового CLI и тестов нет. Соседних принятых дизайнов в проверенной области не обнаружено.

### Причины ревизии

Независимое ревью `ses_eac2f83d1ffenmphj0iEDuer5z` установило:

1. Некоторые Buffer failures не дают сообщения об ошибке; log profile недостаточен.
2. Округление OSC clock накапливается; постоянный допуск 65 frames неверен для всего разрешённого диапазона.

Пользователь подтвердил направление «явные объявления и проверка ресурсов, сохраняя полезный NRT-сценарий». Полный v2 пока не принят.

Включается только `render`. Другие публичные операции, realtime-конверсия, музыкальная оценка, собственный synth engine/DSL, установка зависимостей и sandbox не добавляются.

## 2. Стек, поставка и поддержка

### Alpha support target

| Компонент | Цель первоначальной проверки |
|---|---|
| ОС/архитектура | Linux, Omarchy/Arch, x86_64 |
| Python | CPython 3.14.7 |
| SuperCollider | `sclang`/`scsynth` 3.14.1 одного согласованного пакета |
| NRT | `scsynth` с libsndfile |
| Headless | без GUI session, физического аудиоустройства и realtime-сервера |
| FS | локальная POSIX FS с hard links |

Это target, **не tested matrix**. В исходном read-only discovery наблюдались Omarchy 4.0.4, Python 3.14.7-1 и libsndfile 1.2.2-4; SuperCollider отсутствовал. Новые runtime-проверки этой ревизией не выполнены.

Другие версии первоначально возвращают `unsupported_environment`. Расширение поддержки и обновление security-пинов требуют проверок и фиксации точной сборки; пины не оправдывают бессрочное использование уязвимой версии.

### Технологии и layout

Python stdlib: argv/processes, JSON, Decimal, файловые операции, сигналы, hashing, `wave`, `struct`/`array`, `unittest`. Нет сторонних Python-пакетов, FFmpeg, обязательных plotting libraries, package manager или сетевых запросов при render.

Для canonical resource decoding используется **штатный SC `SoundFile`**, не Python-пакет SoundFile.

Linux process adapter использует libc `prctl` через `ctypes` и стандартные pidfd API. Это настройка собственного процесса, не системы.

```text
skills/supercollider/
  SKILL.md
  scripts/
    sc-tool.py
    scs_tool/
      cli.py
      render.py
      sc.py
      processes.py
      files.py
      wav.py
    prepare-score.scd
  references/
    nrt-contract.md
    render-cli.md
    compatibility.md
  assets/
    minimal-nrt.scd
tests/
  unit/
  contract/
  integration/
```

Новых физических модулей ревизия не требует. Resource preparation находится в `sc.py`/driver, измерение snapshots — в `wav.py`, применение политики — в coordinator.

Переносимый запуск:

```text
python3 -B <skill-root>/scripts/sc-tool.py render ...
```

`sc-tool` — имя интерфейса, не обещание установленной команды. Paths пакета вычисляются относительно пакета. Стиль — PEP 8; проверки — stdlib `unittest` и ручное ревью. Форматтер, линтер, build backend и CI не устанавливаются.

### Зависимости и licensing/security

- CPython — официальный upstream, PSF License v2 и дополнительные notices.
- SC — официальный upstream; README/COPYING определяют GPL v3, отдельные файлы имеют собственные notices.
- CLI использует внешние программы и не копирует их реализацию в MIT-код проекта.
- libsndfile и прочие библиотеки — транзитивные системные зависимости согласованного SC-пакета.

Ранее выполненная ручная проверка официальных лицензий и advisories от 2026-10-19 не доказывает отсутствие CVE. Перед использованием сборки нужны provenance, точные пакеты и применимые upstream/distribution advisories. При render эта проверка не инициирует сеть или обновления.

Сторонних разрешаемых Python-зависимостей нет; искусственный lock-файл не вводится. Системные версии фиксируются в compatibility/evidence.

## 3. Компоненты и владение

| Компонент | Ответственность |
|---|---|
| CLI | request, JSON, exit code |
| Coordinator | состояния запуска, deadline, итоговый успех |
| SC adapter/driver | source contract, canonical preparation, Score, resource schedule, исполнение SC |
| Process owner | собственное дерево процессов и reap |
| File owner | изоляция, staging, evidence files, no-replace publication |
| WAV/snapshot readers | полное чтение, декодирование, измерения |
| Comparison policy | свойства WAV, Buffer-state equality, duration model |

Направление: CLI → coordinator → адаптеры. Интеграции не зависят от харнеса, RIS или художественной задачи. Измерения отделены от решения о соответствии.

Coordinator — единственный владелец mutable-состояния запуска. Нет демона или общего runtime-state между запусками.

## 4. Публичный CLI и параметры

```text
sc-tool render
  --source PATH
  --output PATH
  --duration SECONDS
  --sample-rate INTEGER
  --channels INTEGER
  [--format wav]
  [--seed INTEGER]
  [--timeout SECONDS]
  [--sclang PATH]
  [--scsynth PATH]
  [--sc-class-library PATH]
  [--temp-dir EXISTING_DIRECTORY]
  [--diagnostics-dir EXISTING_DIRECTORY]
  [--json]
```

Сохраняются значения v1:

- source/output/duration/sample-rate/channels обязательны;
- `format=wav`, output — PCM signed 16-bit little-endian;
- `seed=0`, целое `0…2147483647`;
- sample rate — целое `8000…192000`, channels — `1…32`;
- duration — положительное конечное Decimal, максимум 86400 секунд; округлённое N ≥ 1;
- `timeout=120`, диапазон `1…86400` секунд;
- JSON по умолчанию; `--json` совместим с этим поведением;
- повторяющиеся, неизвестные и некорректные параметры — `invalid_input`.

RIFF limit output проверяется по **F_expected** из раздела 8:

```text
2 × channels × F_expected + 4096 ≤ 2^32 − 1
```

RF64 output не поддерживается.

Executable discovery: explicit path, иначе PATH. Env/config не переопределяет запрос результата.

CLI-relative paths разрешаются относительно исходного cwd. Resource-relative paths внутри source contract — относительно `context.source_dir`. Shell expansion, включая `~`, не выполняется.

Все subprocess arguments передаются массивами, без shell. Пути не вставляются в исполняемый SC-код.

**Overwrite отсутствует.** Любой существующий output, включая dangling symlink, защищён. Выбирается новый путь; обёртка не удаляет существующий файл ради повторного запуска.

## 5. Source contract `scs-nrt-source/2`

### 5.1. Форма источника

Доверенный `.scd` возвращает один Function. Function синхронно получает context и возвращает структуру:

```text
contract: "scs-nrt-source/2"
score: штатный Score
resources: массив Buffer-generation declarations
uses: массив dependency declarations
```

Пустые `resources`/`uses` — допустимые явные массивы, не неявное наследование realtime state.

Context сохраняет параметры v1:

```text
contract: "scs-nrt-source/2"
source_path, source_dir
duration: N/sample_rate
frames: N
sample_rate, channels
format: "wav"
sample_format: "int16"
seed
```

Пользовательский output path в context не передаётся.

Источник строит обычные SynthDefs, UGens, события и controls штатным SC. Малого UGen whitelist нет. Обёртка не сочиняет музыку и не изменяет graph.

Источник не запускает процессы/сервер/GUI/сеть, не вызывает `recordNRT`/`play`/`boot`, не ожидает фонового callback и не пишет пользовательский output. Подготовка синхронная, source file не изменяется.

### 5.2. Объявление Buffer-поколения

Каждое поколение имеет:

```text
id: уникальная ASCII-строка [A-Za-z0-9_-]{1,64}
bufnum: целое 0…1023
at: время инициализации, секунды
retire: время освобождения либо null
initial: описание исходного состояния
```

Времена конечны, неотрицательны, не позднее `context.duration`. `retire`, если задан, строго позже `at`.

`initial` имеет одну из форм:

**Файл:**

```text
kind: "file"
path: строка
start_frame: целое ≥ 0, default 0
frames: положительное целое либо null до конца
channels: массив zero-based channel indices либо null все каналы
```

Выбор каналов поддерживает перестановку и повторение. Диапазон должен существовать полностью; молчаливого clamp/zero-padding нет.

**Данные:**

```text
kind: "data"
frames, channels, sample_rate
samples: interleaved FloatArray
```

Размер массива точно равен frames × channels. Значения приводятся к конечным float32.

**Нулевое начальное состояние:**

```text
kind: "zero"
frames, channels, sample_rate
```

Оно пригодно, например, для externally allocated scratch Buffer с дальнейшей обработкой штатными UGens.

Общие representability limits:

- frames > 0;
- frames × channels ≤ `2^31−1`;
- channels > 0, `4×channels ≤ 65535`;
- sample rate — положительное целое ≤ `2^24`, точно представимое float32;
- float32 WAV поколения вместе с резервом 4096 bytes помещается в RIFF.

Это ограничения контейнера/SC-представления, не музыкальный API.

### 5.3. Initial и scheduled generations

Поддерживаются поколения при `at=0` и запланированные позднее. Не требуется загружать все samples до начала музыки.

Один `bufnum` может использоваться повторно, но поколения должны иметь разные `id`, непересекающиеся lifetimes и отдельные snapshots. Перед новой инициализацией адаптер выполняет освобождение прежнего состояния этого Buffer.

Жизнь поколения измеряется также в **реальных NRT-блоках**: B=64 и отображение timestamp → block из раздела 8.

Поколение готово с блока, обрабатывающего его `at`, и недоступно начиная с блока его `retire`. Повторное использование номера допустимо только после завершения всех объявленных использований прежнего поколения. Номинально разные времена внутри одного NRT-блока не считаются безопасным разделением.

### 5.4. Объявления использований и вычисляемые ссылки

Каждое использование содержит:

```text
anchor: [bundle_index, message_index]
from: время начала возможного использования
through: время последнего возможного использования, включительно
resources: массив generation IDs
```

Индексы относятся к зафиксированному `score.score`, до инструментирования; message index не включает timestamp.

Anchor указывает на конкретный `/s_new` или `/s_newargs`. Для каждого такого сообщения требуется покрывающее объявление, включая `resources:[]` для node без внешних Buffer-зависимостей.

Для одного anchor допустимы несколько интервалов: например, смена используемых Buffer через controls. Объявления охватывают также последующие `/n_set`, mapping, bus-driven/computed Buffer references, автоматический lifetime node и обращения при завершении node. Консервативное объявление более широкого интервала допустимо.

**Доверительное обязательство автора:** перечислены все возможные внешние Buffer-зависимости соответствующего node на указанном интервале, и не используются поколения вне объявленных интервалов.

**Технически проверяется:**

- anchor существует и указывает на соответствующие байты сообщения;
- все generation IDs объявлены;
- интервалы корректны и попадают в lifetime поколения;
- каждое объявленное использование начинается не раньше readiness;
- overlap/reuse проверяется по NRT-блокам;
- декларации связаны с точным source Score и итоговым Score через manifest и hashes.

**Не обещается:** универсально вывести dependencies из произвольного UGen graph или доказать правдивость вычисляемой Buffer-ссылки. Это semantic precondition доверенного source contract, как отсутствие скрытых побочных эффектов в `.scd`, а не sandbox.

Результат прямо указывает `dependency_coverage: "trusted-declared"`; он не заявляет статически доказанную полноту dependencies.

### 5.5. Материальные ограничения профиля

Следующие ограничения входят в предлагаемый v2 и требуют принятия вместе с ним:

- Buffer initialization/reload/free выполняется через declarations, не raw `/b_*`.
- Streamed file handles и `leaveOpen=true` не поддерживаются этим verifier: `/b_write` способен закрыть существующий `buf->sndfile`. Их нельзя незаметно инструментировать.
- Raw `/b_gen`, `/b_set[n]` и иные server-side resource preparation операции заменяются заранее подготовленным `data`/`file` состоянием. Автоматическая конверсия не обещается.
- Не поддерживаются opaque plugin commands и скрытые completion programs.
- Поддерживается **initial readiness**, не повторная проверка каждого sample read после намеренных DSP-изменений Buffer.
- Внутренние DSP-ресурсы вроде LocalBuf не выдаются за внешние проверенные Buffer-поколения. Их обычное штатное использование не запрещено; универсальная проверка их allocation не обещается.
- Неподдерживаемый resource mode диагностируется, а не проходит с ослабленным успехом.

Обычные samples через Buffer/PlayBuf/BufRd, scratch Buffer, native controls, множество SynthDefs, scheduling и намеренное изменение Buffer DSP сохраняются.

### 5.6. Минимальный пример без внешних ресурсов

```supercollider
{ |ctx|
    var score = Score([
        [0.0, [\d_recv, SynthDef(\scsMinimal, {
            Out.ar(
                0,
                Array.fill(ctx[\channels], {
                    SinOsc.ar(480, 0, 0.1)
                })
            )
        }).asBytes]],
        [0.01, [\s_new, \scsMinimal, 1000, 0, 1]]
    ]);

    (
        contract: "scs-nrt-source/2",
        score: score,
        resources: [],
        uses: [
            (
                anchor: [2, 0],
                from: 0.01,
                through: ctx[\duration],
                resources: []
            )
        ]
    )
}
```

`Score` добавляет default group; anchor проверяется относительно фактически возвращённого массива. Пример становится «проверенным» только после интеграционного теста compiler/serialization.

Для sample-сценария source объявляет file-generation, использует её `bufnum` обычным `/s_new` argument и добавляет generation ID к соответствующему `uses`. Обёртка не предоставляет музыкальных конструкторов.

Language seed устанавливается перед вызовом Function. Серверные random UGens требуют явного штатного seed в пользовательском graph; language seed не заменяет его.

## 6. Подготовка, canonical data и бинарное enforcement

### 6.1. Driver и окружение

Запускается пакетный driver:

```text
sclang -D -a -l <run-config> <driver>
  <source> <score-path> <status-path> <run-token>
  <N> <sample-rate> <channels> <seed>
```

Значения читаются из `thisProcess.argv`, не из сгенерированного кода.

Конфигурация включает только штатную SCClassLibrary выбранной установки, без пользовательских Quarks/Extensions. Обнаружение библиотеки/локальной справки и explicit `--sc-class-library` сохраняются из v1. Отсутствие локальной справки сообщается как ограничение.

Child environment:

- отдельные HOME/XDG_CONFIG_HOME/XDG_DATA_HOME/XDG_CACHE_HOME/TMPDIR;
- закрытый stdin;
- очищенные влияющие SC overrides;
- `QT_QPA_PLATFORM=offscreen`;
- без автоматического отключения Chromium/WebEngine sandbox.

Это не доказательство headless readiness.

### 6.2. Driver flow

Driver:

1. Проверяет входы, компилирует source и получает Function.
2. Устанавливает seed, однократно вызывает Function.
3. Проверяет структуру результата, Score, declarations и uses.
4. Фиксирует исходный Score и его anchor map.
5. Подготавливает reference/canonical resources.
6. Формирует instrumented Score с определённым ниже порядком.
7. Записывает исходный и итоговый Score штатным `Score.write`, clock tempo=1.
8. Закрывает все файлы, записывает manifest и status.
9. Явно завершает `sclang`.

Пользовательский Function автоматически не повторяется.

Manifest содержит только ограниченные scalar/array/map данные. JSON encoding — инфраструктурный serializer с escaping; нет `eval`/исполнения сериализованных SC-выражений или предположения о наличии стороннего JSON Quark.

### 6.3. Canonical preparation

Для file-generation:

1. Исходный файл копируется в приватное пространство запуска.
2. Проверяются ожидаемая полнота копии и стабильность исходника; изменение входа приводит к отказу, не к заявлению о фиксированном оригинале.
3. Штатный `SoundFile` читает staged copy порциями в FloatArray.
4. Учитывается **фактический размер массива после `readData`**, проверяются header count, выбранный диапазон, каналы и полный объём.
5. Выбранные данные экспортируются как reference float32 little-endian через штатный `File.writeLE`.
6. Те же данные записываются в canonical WAV IEEE float32, без resampling, gain или musical transformations.
7. Все файлы закрываются.

Для `data` используется переданный FloatArray, для `zero` — определённое нулевое состояние. Для них также формируется reference; zero reference допускает потоковое сравнение без огромного массива в памяти.

После выхода driver CLI **полностью** читает reference и canonical WAV:

- проверяет counts, структуру, конечность samples;
- сравнивает все float32 values;
- считает hashes;
- проверяет canonical rate/channels/frames.

Boolean от `writeData`, длина файла или успешный driver exit этого не заменяют. Short write canonical/reference приводит к отказу до NRT.

Float32 equality точная, без epsilon; `+0` и `−0` считаются одинаковым значением. Для нормализованного sample hash оба нуля кодируются как `+0`. NaN/Inf в initial resource data отклоняются как недопустимый вход. Это не обещание проверки нечисловых значений произвольного DSP.

Имена canonical/reference/snapshot файлов назначает адаптер. Source не задаёт snapshot path.

### 6.4. Instrumented order

Driver сохраняет порядок пользовательских сообщений в фактическом исходном Score. При одинаковом timestamp формируется следующий явный порядок:

1. Retirement прежних поколений.
2. Инициализации новых поколений в порядке declarations.
3. Непосредственно после каждой инициализации — её snapshot.
4. Пользовательские сообщения этого timestamp, в исходном порядке.
5. На terminal timestamp после пользовательских сообщений — завершающий no-op.

Resource initialization:

```text
/b_free bufnum
/b_allocRead bufnum canonical-path 0 -1
/b_write bufnum snapshot-path WAV float -1 0 0
```

Для zero-generation вместо чтения:

```text
/b_free bufnum
/b_alloc bufnum frames channels 0 sample-rate
/b_write bufnum snapshot-path WAV float -1 0 0
```

Числовой `0` в `/b_alloc` — отсутствие completion message перед explicit sample rate, не OSC program.

Canonical channel selection устраняет необходимость `/b_allocReadChannel` и его дополнительной временной allocation. Allocation настоящего Buffer всё равно выполняется в NRT и проверяется snapshot.

На retirement выполняется `/b_free`. Файлы закрытых sample Buffers не имеют streaming handle.

В pinned NRT sequenced commands проходят `CallEveryStage` синхронно; `PerformOSCBundle` обрабатывает сообщения последовательно, и `World_Run` вызывается после обработки готовых команд. Между init и snapshot нет пользовательского сообщения или DSP block.

Система не останавливает рендер для интерактивного callback: проверка snapshots производится после завершения. При неготовом ресурсе может существовать partial main WAV, но ready он не станет.

### 6.5. Native command boundary

Для пользовательского Score поддерживаются:

```text
/d_recv, /d_free
/s_new, /s_newargs
/n_free, /n_run, /n_set, /n_setn, /n_fill
/n_map, /n_mapn, /n_mapa, /n_mapan
/n_before, /n_after, /n_order
/g_new, /g_head, /g_tail, /g_freeAll, /g_deepFree
/c_set, /c_setn, /c_fill
cmd_none
```

Это ограничение инфраструктурных команд, **не UGen whitelist**.

CLI разбирает фактически записанные исходный и итоговый OSC Score:

- bounds, lengths, padding, timestamps, types и полное потребление bytes;
- numeric opcodes нормализуются по pinned `SC_OSC_Commands.h`;
- для разрешённых команд проверяется соответствующая форма аргументов;
- `/d_recv` допускает только SynthDef blob и отсутствие completion; нулевой placeholder можно нормализовать в отсутствие completion;
- SynthDef blob проверяется как штатный SCgf, включая counts, names, controls, variants и ссылки, без списка «разрешённых художественных UGens»;
- другие opaque blobs, nested bundles/completion messages и trailing arguments отклоняются;
- `/b_*`, `/cmd`, `/u_cmd`, `/n_cmd`, `/error`, `/quit`, scheduler-clearing и другие неподдерживаемые команды в source отвергаются;
- сгенерированные `/b_*` в final Score должны **точно** соответствовать manifest, включая порядок, поколения и пути;
- остальные final messages должны совпадать с source Score; произвольной вставки или удаления пользовательских событий нет.

Таким образом, скрытый `/b_allocRead` в completion blob не обходит declarations. Разбор только текстовых имён или верхнего уровня недостаточен.

Нет fallback «не смогли проверить blob — всё равно запустить».

### 6.6. Подтверждение подготовки

Status protocol:

```text
SC_TOOL<TAB>2<TAB>TOKEN<TAB>PREPARED<TAB>N<TAB>RATE<TAB>CHANNELS<LF>
```

или:

```text
SC_TOOL<TAB>2<TAB>TOKEN<TAB>ERROR<TAB>ERROR_KIND<LF>
```

Kinds: `source_compile`, `source_eval`, `source_contract`, `resource_prepare`, `score_write`.

Подготовка подтверждена только при:

- полном соответствующем record;
- нормальном exit `sclang`;
- отсутствии наблюдаемых ошибок;
- проверенных reference/canonical data;
- проверенном binary Score/manifest/anchor correspondence;
- завершённой очистке процессов подготовки.

PREPARED — не подтверждение NRT или Buffer readiness. Отсутствие достаточного record даёт `sclang_unconfirmed`; точная неизвестная причина не выдумывается.

## 7. NRT, resource evidence и критерий успеха

### 7.1. Исполнение

Сохраняется прямой запуск v1:

```text
scsynth -N <score.osc> _ <private-staging.wav>
  <sample-rate> WAV int16
  -i 0 -o <channels> -z 64 -D 0 -R 0 -V 0
```

Нет shell. `_` отключает streaming input file. `-D 0` исключает preloaded пользовательские SynthDefs.

Остальные server defaults фиксируются manifest выбранной сборки. Pinned default `mNumBuffers=1024` обосновывает допустимые bufnum. Произвольные additional server flags не вводятся.

### 7.2. Полная проверка snapshots

Каждое поколение получает уникальный path в новом приватном каталоге запуска. До NRT snapshot отсутствует; reference/canonical и snapshot имеют разные пути и роли.

После завершения CLI:

1. Проверяет regular file без symlink-подмены в доверенном owned directory.
2. Полностью проверяет RIFF/WAVE IEEE float32: fmt, rate, channels, block align, data bounds и padding; float subtype extensible допустим.
3. Декодирует весь payload через `struct`/`array`, не Python `wave`, который здесь недостаточен.
4. Проверяет фактические frames/sample count и конечность.
5. Сравнивает **каждое** sample value с canonical reference по политике §6.3.
6. Записывает expected/measured metadata и hashes в evidence manifest.

Snapshot frames должны точно совпасть с поколением; output-duration tolerance к нему неприменим.

Wrong/missing/truncated snapshot, неправильные каналы, порядок samples или содержимое запрещают success даже при code 0 и идеальном main WAV.

### 7.3. Что доказывается

Snapshot наблюдает настоящий Buffer данного NRT в точке между его initialization и первыми consumer commands/DSP. `BufAllocReadCmd::Stage3` переносит подготовленные данные в runtime Buffer до последующего сообщения; `/b_write` читает это фактическое состояние.

Для known silent allocation failure свежий или предварительно освобождённый Buffer не предоставляет ожидаемый положительный объём данных. Snapshot отсутствует, повреждён, имеет неверные metadata/content либо процесс падает — ни один случай не становится ready.

Snapshot generation identity обеспечивается manifest, точным местом команды, новым run directory и уникальным именем. Старый файл или snapshot другого поколения не принимается.

Это **state-readiness evidence**, не proof каждого внутреннего вызова. Если история неуспешного внутреннего действия оставила состояние, полностью равное требуемому, сравнение состояния не различает эти истории. Любая доступная диагностика ошибки всё равно запрещает success.

Намеренное последующее изменение Buffer DSP допустимо. Snapshot не выдаётся за доказательство последующих вычислений, музыкальной корректности или каждого allocation внутри произвольного UGen.

### 7.4. Missing SynthDefs и обычные errors

Исходный SCgf и command stream проверяются до запуска; `/s_new` должен ссылаться на definition/variant, доступный по предшествующему `/d_recv` с учётом `/d_free`.

Фактическое отсутствие SynthDef в `scsynth` дополнительно диагностируется штатным `/s_new`: pinned handler печатает ошибку и возвращает failure. Initial command allocations/ошибки handler проходят через `SC_LibCmd::Perform`; GraphDef receive exceptions также печатаются.

Это не заменяется проверкой «node существует». Не вводится trace всех пользовательских graph и не обещается доказательство каждого UGen constructor.

### 7.5. Логи

Log profile остаётся дополнительным fail-closed контролем:

- `FAILURE IN SERVER`, `ERROR:`, `NRT synthesis failed`, GraphDef exceptions и известные resource failures — отказ;
- нормальные progress lines распознаются;
- неизвестная существенная диагностика — `nrt_unconfirmed`;
- допустимые warnings выделяются явно;
- потеря/неполнота logs не скрывается.

Log profile не используется как доказательство отсутствующего сообщения о Buffer failure. Полный профиль и его реальные fixtures подтверждаются для поддерживаемой сборки до заявления пригодности.

Как в v1, непривычный пользовательский вывод, например Poll, может привести к безопасному unconfirmed result.

### 7.6. Success conjunction

Успех требует одновременно:

1. Подтверждённой подготовки и соответствия поддерживаемому source contract.
2. Нормального завершения `scsynth`, code 0.
3. Полных logs без ошибок/неподтверждённой существенной диагностики.
4. Полного matching snapshot evidence всех объявленных поколений.
5. Полностью декодированного соответствующего main WAV.
6. Завершения собственного process tree.
7. Безопасной публикации и обязательной очистки.

Code, file existence, completion, `/sync`, metadata probes или graph trace по отдельности недостаточны.

Неполнота семантических declarations не объявляется автоматически обнаруживаемой. Гарантии относятся к доверенному source, соблюдающему опубликованный контракт; универсальный sandbox/dependency verifier не обещается.

## 8. Duration model и проверка main WAV

Из исходного Decimal D и sample rate R:

```text
N = ROUND_HALF_UP(D × R)
nominal_duration = N/R
```

Driver задаёт terminal timestamp равным nominal duration. CLI читает целый 32.32 timestamp T из фактически записанного terminal bundle и проверяет рационально:

```text
abs(T − N × 2^32/R) ≤ 1 OSC tick
```

Для pinned SC, B=64, Q=`2^32`:

```text
q = floor(B × Q/R)
K = max(1, (T + q − 1) // q)
F_expected = B × K
```

Это соответствует накоплению целого `oscInc`, а не только округлению одного блока. Условия модели: валидный монотонный Score, проверенный terminal bundle, отсутствие premature quit/скрытых scheduled completion programs, block size 64 и подтверждённая pinned реализация.

Timestamp → execution block для resource lifetimes использует ту же функцию K. При retirement в блоке K ресурс уже недоступен DSP этого блока. Для usage `[from,through]` оба конца переводятся в блоки; все блоки использования должны принадлежать поколению.

При целых R в диапазоне CLI `R×2^-32` точно представимо; ошибка double division недостаточна, чтобы изменить floor относительно указанной рациональной формулы. Новая реализация SC требует повторной проверки модели.

Main WAV соответствует длительности только при:

```text
measured_frames == F_expected
```

Допуск относительно предсказанного значения — 0 frames.

Отдельно сообщаются:

- requested D;
- target N и nominal N/R;
- expected F_expected/R;
- expected padding `F_expected−N`;
- реально измеренная длительность.

Примеры:

| R | D | q | T | F_expected |
|---:|---:|---:|---:|---:|
| 48000 | 2 | 5726623 | 8589934592 | 96064 |
| 192000 | 1000 | 1431655 | 4294967296000 | 192000128 |

Обёртка не обрезает output и не дописывает тишину. RIFF limit вычисляется по F_expected.

### Main WAV reader

Сохраняется PCM16 reader v1:

1. RIFF/WAVE, bounds, размеры/padding, fmt/data, block align и byte rate.
2. PCM16 либо PCM subtype extensible; не compressed/float/RF64 output.
3. Открытие через `wave`.
4. Чтение всего payload ограниченными порциями.
5. Декодирование каждого signed little-endian sample.
6. Проверка кратности frame size, отсутствия short read, соответствия фактических frames заголовку.
7. Измерение duration из декодированных frames.
8. Точное сравнение rate/channels и сравнение frames с моделью.

Повреждение/неполнота — `audio_invalid`; правильный WAV с неверными свойствами — `audio_mismatch`.

Пик, клиппинг, тишина и художественная оценка не становятся публичными критериями успеха.

## 9. Deadline, cancellation и процессы

Сохраняется политика v1. Monotonic deadline охватывает discovery, source/canonical preparation, NRT, snapshots и audio checks. Version probe ограничен оставшимся deadline и максимумом 2 секунды. Cleanup budget — отдельные 5 секунд.

CLI — отдельный process owner:

- собственный `PR_SET_CHILD_SUBREAPER`;
- отдельные sessions/process groups основных детей;
- учёт direct/adopted descendants;
- pidfd и проверка принадлежности, без сигналов старому переиспользованному PID;
- wait/reap, включая осиротевших потомков;
- завершение leader не означает пустое дерево.

При error/timeout/SIGINT/SIGTERM прекращаются новые стадии и публикация, направляется TERM собственным детям, затем KILL оставшимся; adopted children также очищаются.

Нет `pkill`, `killall`, `Server.killAll` и поиска процессов по имени.

stdout/stderr дренируются параллельно. Лимит — 16 MiB на поток/стадию; превышение даёт `resource_limit`, не тихую потерю ошибок.

Контракт не является защитой от fork bomb/вредоносного `.scd`. SIGKILL самого CLI, падение ОС и неубиваемые kernel tasks не выдаются за гарантированно очищенные случаи. Наблюдаемый cleanup failure запрещает success, возвращает owned PID и unfinished actions.

Дополнительный resource I/O не разрешает автоматически увеличить timeout.

## 10. Файлы, публикация и partial results

Сохраняются гарантии v1:

- уникальные private run directories mode 0700, files 0600;
- temp/diagnostics flags задают существующие base directories;
- default base — system temp; retention location всегда сообщается;
- output parent должен существовать;
- staging main WAV находится на FS output.

В owned resources входят также staged input copies, reference payloads, canonical files, source/final Score, manifests и snapshots. Их роли и cleanup фиксируются при создании.

Source и sample input files открываются как inputs, не изменяются. Проверяются canonical paths/identity. Output не может повредить source или ресурс через path alias, symlink или hardlink.

Существующий output определяется `lstat`, включая dangling symlink. Publication — atomic hard link из проверенного staging в отсутствующий target. Нет truncate или unsafe copy fallback. Необходимая FS semantics отсутствует — file error.

Output directory удерживается descriptor. Новый конкурентный target не перезаписывается. Hostile переименование всей иерархии каталогов не входит в модель доверенной локальной FS.

### Retention

При success сохраняются main WAV и полезная компактная диагностика: manifests, measurements, hashes, versions, logs. Большие canonical/reference/snapshot intermediates после проверки удаляются; manifest записывает измерения, hashes и состояние удаления.

При failure сохраняются полезные доступные logs/status/manifests, Score и относящиеся к отказу resource evidence/partial WAV. Остальное disposable удаляется.

Невозможность сохранить evidence или очистить owned файл сообщается с фактическим path и unfinished action. Очистка не использует произвольные пути из source/logs.

Если output уже опубликован, а cleanup/cancel дал отказ: artifact имеет `published=true`, `verified=true`, но не входит в `ready`. Опубликованный пользовательский path автоматически не удаляется.

Нет автоматического повтора source, общего rollback или удаления прежней диагностики. Для долговременного retention выбирается diagnostics-dir; system temp может очищаться ОС.

## 11. JSON schema 2 и exit codes

Одна компактная UTF-8 JSON-строка в stdout после финализации. Raw SC streams находятся в logs. stderr — только аварийная собственная диагностика невозможности выдать результат.

Пример success без внешних Buffer:

```json
{
  "schema_version": 2,
  "operation": "render",
  "run_id": "unique-id",
  "status": "success",
  "stage": "complete",
  "exit_code": 0,
  "requested": {
    "source": "/absolute/source.scd",
    "output": "/absolute/result.wav",
    "duration_seconds": "2",
    "sample_rate": 48000,
    "channels": 2,
    "format": "wav",
    "sample_format": "int16",
    "seed": 0,
    "timeout_seconds": 120
  },
  "effective": {
    "source_contract": "scs-nrt-source/2",
    "target_frames": 96000,
    "nominal_duration_seconds": 2.0,
    "terminal_osc_ticks": 8589934592,
    "osc_increment_ticks": 5726623,
    "block_size": 64,
    "expected_frames": 96064,
    "expected_padding_frames": 64,
    "expected_duration_seconds": 2.001333333333333,
    "duration_tolerance_frames": 0
  },
  "measured": {
    "frames": 96064,
    "duration_seconds": 2.001333333333333,
    "sample_rate": 48000,
    "channels": 2,
    "format": "wav",
    "sample_format": "int16"
  },
  "resource_evidence": {
    "dependency_coverage": "trusted-declared",
    "dependencies_inferred": false,
    "generations": 0,
    "verified_generations": 0,
    "manifest": "/absolute/diagnostics/resources.json"
  },
  "artifacts": {
    "ready": [
      {
        "path": "/absolute/result.wav",
        "kind": "audio",
        "format": "wav",
        "verified": true,
        "published": true
      }
    ],
    "partial": []
  },
  "diagnostics": {
    "directory": "/absolute/diagnostics",
    "logs": [],
    "processes": []
  },
  "environment": {
    "tool": "package-version",
    "python": "3.14.7",
    "sclang": "3.14.1",
    "scsynth": "3.14.1",
    "platform": "linux-x86_64"
  },
  "warnings": [],
  "errors": [],
  "unfinished_actions": []
}
```

Paths/version placeholder иллюстративные, не продуктовые absolute paths.

Resource manifest содержит для каждого generation: bufnum, at/retire и block lifetime, source/canonical/reference/Score hashes, expected/measured properties, snapshot hash, comparison verdict и retention state. Summary не заменяет этот evidence.

Unknown fields — null. Error/warning:

```text
{code, stage, message, hint, details}
```

Partial artifact:

```text
{path, kind, verified, published, reason}
```

Statuses: `success`, `error`, `timeout`, `cancelled`.

Stages: `input`, `dependencies`, `prepare`, `nrt`, `resources`, `audio`, `publish`, `cleanup`, `complete`.

| Exit | Основной результат |
|---:|---|
| 0 | success |
| 2 | invalid_input, source_contract, invalid resource declaration/input |
| 3 | dependency_missing, dependency_unexecutable, unsupported_environment |
| 10 | sclang_error, sclang_unconfirmed |
| 11 | nrt_error, nrt_unconfirmed, resource_evidence_missing/invalid/mismatch |
| 12 | audio_invalid |
| 13 | audio_mismatch |
| 14 | file_error, output_exists |
| 20 | wrapper_error |
| 21 | resource_limit |
| 24 | timeout |
| 25 | cleanup_failed |
| 130 | cancelled/SIGINT |
| 143 | cancelled/SIGTERM |

Cleanup failure определяет code 25/status error; исходная причина сохраняется. Иначе действует первая остановившая исполнение причина. Normal post-NRT checks: process/log evidence → resources → main audio → publish/cleanup.

Закрытый stdout pipe физически исключает гарантию JSON; это transport failure, не success.

Source contract 1→2 и schema 1→2 несовместимы; fallback на v1 отсутствует. Опубликованной реализации v1 пока нет. Дальнейшие несовместимые изменения требуют нового контракта/явного перехода.

## 12. Test seams и AC

### Seams

- `validate_request` — нормализованный request.
- `prepare_score` — source evaluation и подготовленные файлы.
- `validate_source_plan` — declarations, anchors, binary command boundary.
- `read_canonical_resource` — полные reference/canonical measurements.
- `validate_instrumentation` — точное source/final correspondence и lifecycle blocks.
- `run_nrt` — process/log evidence.
- `read_buffer_snapshot` — фактические metadata и все float32 values.
- `compare_resource_state` — equality/ошибки.
- `read_wav`/`compare_audio` — main measurements и expected frames.
- `publish_no_replace`/`finalize_run` — publication/cleanup evidence.

Pure tests отделены от процессов/SC. Stubs дополняют, не заменяют настоящую интеграцию.

### AC → oracle

| AC | Проверка |
|---|---|
| 001 | Настоящий minimal example, 2s/48000/stereo: PCM16, ровно 96064 decoded frames, JSON ready |
| 002 | Неверный Function/result/Score, invalid declarations/anchors, forbidden commands/completion: предметный отказ |
| 003 | Missing SynthDef, absent sample, realtime dependency; known silent Buffer failure model: нет success при исправном main WAV |
| 004 | Missing/non-executable dependencies, unsupported versions/NRT build: dependency error, без установки |
| 005 | Syntax/runtime/class-library/server/wrapper failures и insufficient resource evidence различимы |
| 006 | Hanging prepare/NRT, короткий timeout: owned tree reaped, чужой process жив |
| 007 | Exit 0 без output, broken RIFF, truncated data/short read: audio_invalid |
| 008 | F_expected±1, неверные rate/channels: mismatch с target/expected/measured, ready пуст |
| 009 | Absolute/relative paths, spaces/quotes/метасимволы/newline для source/sample/output: данные, не команды |
| 010 | Existing output, symlink/dangling symlink/hardlink alias: файлы и source неизменны |
| 011 | Parallel success/failure, одинаковый target: isolation, один publish winner, snapshots не смешиваются |
| 012 | Success/error/SIGINT/SIGTERM на всех стадиях: учтённые resources/processes, доступные diagnostics |
| 013 | Default compact JSON schema 2, согласованные codes/status/artifacts, raw SC output отделён |
| 014 | Partial WAV или missing resource evidence; publication-before-cleanup failure: честные partial/published/unfinished |
| 015 | Настоящий render без plotting packages, Quarks и сети; sample scenario также независим |
| 016 | Agent Skills metadata/links и отдельно согласованный harness scenario; без hooks/music/Remotion |
| 017 | Fixed source/Score/resource hashes, seed, params, versions; frames по модели и применимые sound metrics |
| 018 | Нет package-manager/global config side effects; HOME/XDG изолированы, owned writes перечислены |

### Обязательные resource regressions

1. Nonuniform stereo sample, выбор/перестановка каналов, full snapshot equality.
2. Scheduled generation и reuse bufnum с разными данными.
3. Main WAV правильный, snapshot нулевой при ожидаемом nonzero payload — отказ.
4. Correct metadata, wrong sample/channel order — отказ.
5. Missing/truncated snapshot при code 0/completion — отказ.
6. Старый path/run/generation, duplicate snapshot mapping — отказ.
7. Canonical/reference short write и source short read — отказ до NRT.
8. Raw `/b_allocRead`, numeric alias, вложенный completion, extra blob/trailing arguments — отказ до исполнения.
9. Same-timestamp resource/consumer — правильный order; same-block unsafe reuse — отказ.
10. Declared DSP-mutated Buffer: initial state проверен; последующий DSP output не выдаётся за проверенный snapshot.
11. Missing SynthDef и фактический server error при нормальном WAV — отказ.
12. Zero input не используется как доказательство истории каждого внутреннего вызова.
13. Contract test моделирует тихий allocation failure без намеренного OOM машины.
14. Полнота вычисляемых dependencies обозначена trusted, а не ложно доказана тестом parser.

### Timing regressions

- Пороговые T около q и кратных q; минимальный N=1.
- Независимая bounded модель цикла `oscTime += q` против формулы.
- 192000/1000 → 192000128 frames.
- 48000/2 → 96064 frames.
- High rates, long durations, RIFF boundary.
- Неверный terminal T не принимается благодаря совпавшему подставному WAV.
- Позднее разрешённый настоящий long render; его отсутствие — skip, не pass.

### Sound fixtures

Небольшие собственные fixtures под MIT, без сторонних samples.

- Minimal: 480 Hz, amplitude 0.1, nominal 2s, начало после 0.01s; участок 0.1–1.9s, RMS `0.1/√2 ±0.002`, sine/cosine projection на 480 Hz.
- Seeded phase/score fixture: повтор на одной объявленной среде, RMS difference ≤ `1e−4`, sample RMSE ≤ `2/32768`.
- Для Buffer проверки сравниваются initial float32 values точно; это не межплатформенный sound oracle.
- Межплатформенная побитовая идентичность main render не требуется.

### Headless evidence gate

До объявления AC-001/015 выполненными:

- точная Linux/architecture/package matrix;
- GUI session env отсутствует;
- аудиоустройства недоступны;
- realtime-сервер отсутствует и не стартует;
- внешняя сеть недоступна;
- HOME/XDG изолированы;
- команда, ревизия, inputs, logs, pass/fail/skip зафиксированы.

Runner availability не предполагается. Реальная Agent Skills/harness проверка требует отдельного согласования сценария, среды и стоимости.

## 13. Архитектурное соответствие и применимость требований

| Норма | Решение |
|---|---|
| A-01 | Штатные SC Score/DSP, без музыкальной DSL, облака или харнес-зависимости |
| A-02 | CLI→интеграции; measurements отдельно от comparison; optional graphics отсутствуют в dependency path |
| A-03 | Контракты и errors заданы; resource state evidence отделён от exit/log/DSP-proof |
| A-04 | Run ownership всех canonical/snapshot/process resources, protected publication |
| A-05 | Partial/unfinished явны; нет autoretry/общего rollback/установок |
| A-06 | Negative seams для silent failures, same-NRT evidence и headless integration |
| A-07 | Существенный revision требует отдельного принятия |
| E-01–05 | Пины, dependency limits, воспроизводимые tests/evidence и независимое ревью |

Fitness: нет RIS/OpenCode/network/plotting imports в runtime path, `shell=True`, mass process killing или package-manager invocations. Все created paths имеют owner/lifetime.

R-01–R-13 и AC-001–018 не изменены. R-01/04/05/12 уточняются supported instrumented source contract; R-03/10 — точной duration semantics и честным evidence scope.

Принятые требования не обещают proof каждого произвольного DSP-вызова. V2 не вводит это обещание. Но известные неготовые обязательные Buffer states больше не пропускаются по отсутствию logs.

## 14. Альтернативы, риски и совместимость

### Альтернативы

- `recordNRT` напрямую: отклонён из-за shell construction/ownership, как в v1.
- Только static input validation: не закрывает фактический allocation.
- Completion/sync/metadata probes: не закрывают silent failure с корректными metadata.
- Trace каждого graph: не доказывает resource bytes и не нужен для принятой границы.
- Малый UGen whitelist: отвергнут пользователем и не используется.
- Universal verification engine: не вводится.
- `/b_alloc`+огромный `/b_setn` Score: возможен, но менее экономичен; canonical file + full snapshot сохраняет тонкость механизма.
- Внешние SoundFile bindings/FFmpeg: не нужны.
- Обязательные cgroups/container: не добавляются.

### Существенные риски

1. Semantic completeness dependencies доверяется автору; не выводится из arbitrary DSP.
2. Snapshot I/O повышает disk/time cost; timeout и file errors остаются явными.
3. Новые streaming/raw preparation ограничения требуют принятия и документации.
4. Exact float32 roundtrip, command ordering и timing model требуют настоящих integration checks.
5. SC log profile версиозависим; unknown diagnostics могут дать безопасный ложный отказ.
6. Установленный SC/headless runner и security evidence пока не подтверждены.
7. Source не sandbox; malicious files/programs/environment не покрываются.
8. Retained diagnostics могут занимать место; автоматический TTL отсутствует.

### Устойчивые публичные решения

- structured Function result с native Score/resources/uses;
- trusted-declared coverage вместо universal dependency inference;
- full same-NRT snapshot readiness;
- scheduled generations и block-based lifetime;
- source/schema version 2;
- requested/nominal/expected/measured duration;
- PCM16 output, отсутствие overwrite;
- process ownership и no-replace publication.

Они требуют независимого ревью и отдельного принятия. Внутреннее размещение функций по существующим модулям обратимо.

Новых конфликтующих соседних контрактов в предоставленной области не обнаружено. Принятие v1 остаётся историческим; автоматического переноса на v2 нет.

## 15. Источники, доказательства и граница готовности

Все SC-ссылки ниже относятся к официальному repository:

`https://github.com/supercollider/supercollider/blob/426edf6d8742e1cc3bd85b51ca0c4e595d37a903/`

| Источник | Существенное свидетельство |
|---|---|
| `server/scsynth/SC_World.cpp:1047–1053` | `bufAlloc` failure без обязательной печати |
| `SC_SequencedCommand.cpp:485–538,734–815` | silent alloc/channel-copy paths и продолжение стадий |
| `SC_SequencedCommand.cpp:151–169` | NRT `CallEveryStage` |
| `SC_SequencedCommand.h:38–54` | вызов sequenced commands и propagation initial errors |
| `SC_CoreAudio.cpp:226–240` | последовательный порядок сообщений bundle |
| `SC_CoreAudio.cpp:295–305` | completion program исполняется как OSC packet; его нельзя игнорировать при проверке |
| `SC_SequencedCommand.cpp:395–418` | освобождение и сброс Buffer |
| `SC_SequencedCommand.cpp:527–538` | commit Buffer до следующей команды |
| `SC_SequencedCommand.cpp:1009–1062` | snapshot читает реальное состояние; write return недостаточен |
| `SC_MiscCmds.cpp:750–779` | missing SynthDef и `/s_new` errors |
| `SC_Lib.cpp:184–202` | command failures в diagnostics |
| `SC_GraphDef.cpp:589–597` | GraphDef receive exceptions |
| `SC_World.cpp:630–751` | null replies, OSC increment, last block и output close |
| `lang/LangPrimSource/OSCData.cpp:278–304` | binary 32.32 timestamp |
| `Score.sc:140–161` | штатная запись списка в OSC с clock tempo |
| `PyrFilePrim.cpp:1758–1819` | реальные read counts и недостаточность write boolean |
| `Common/Unix/UnixFILE.sc:62–73` | `writeLE` raw arrays |
| `SC_WorldOptions.h:39–49` | pinned defaults |
| `HelpSource/Reference/Synth-Definition-File-Format.schelp` | штатный SCgf binary contract |

Сохранённые local spec/design/decisions прочитаны полностью. Полные product/rules использованы как применимые нормативные входы исходного проектирования; v2 не предлагает их менять.

### До признания пригодности

1. Независимое ревью полного v2, особенно R-01/R-02, trusted coverage и completion enforcement.
2. Отдельное человеческое принятие полного текста, включая ограничения §5.5.
3. Подтверждение точной SC/runtime сборки, dependency provenance/security.
4. Сверка с локальной справкой выбранной установки.
5. Подтверждение headless runner.
6. По отдельному разрешению — actual compiler, canonical read-back, same-NRT snapshot, scheduling, silent-failure contract tests, timing, WAV/process/file checks.

Source evidence не называется выполненной интеграцией. Недостаточное evidence даёт отказ, не ослабление success.

Если пользователю необходимы streaming handles, raw opaque resource preparation или технически доказанная полнота arbitrary computed dependencies, этот контракт недостаточен: требуется отдельное решение, не скрытый fallback.

Дизайн не разрешает запись, install/config, experiments, implementation/decomposition, tracker, commit/push или publication.

**Конец полного кандидата `nrt-render-design-v2`.**
