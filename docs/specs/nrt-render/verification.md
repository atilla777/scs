# nrt-render — verification evidence v1

Дата: 2026-10-20. Это компактный переносимый отчёт наблюдений, не решение
о принятии требований/дизайна, независимое ревью или завершение feature.
Публикацию этого локального результата выполняет пользователь.

## Ревизии и применимость

- Требования `nrt-render-requirements-v1` и дизайн `nrt-render-design-v2`:
  commit `3755ca963bd198bd9ec60acb0c23c858410cfd34`, полные
  [spec.md](spec.md), [design.md](design.md), отдельные решения
  [decisions.md](decisions.md). Их содержание/принятие здесь не меняется.
- Проверенный implementation/package commit:
  `539b66723fee1d37b0e4d1eb3b0648e5f82eefb7`, tree
  `ac80d9dc56e625925a258a906903b4a32f8e0115`.
- SKILL.md SHA-256:
  `c11e847dbda012beaa8c6c6e4aa51a7ced223594c54500be3a2d10209a76d869`;
  fixture `skills/supercollider/assets/minimal-nrt.scd` SHA-256:
  `9ddc8bd2a8a347cb9ead7923f8eb5c8b951af0bca23f72874a275fa0778136e9`.
  Все перенесённые package bytes/modes сверены с implementation commit до/после
  smoke, без изменений. Runtime, tests, SKILL и fixture в текущем docs-only
  дополнении неизменны. README/compatibility теперь описывают эти наблюдения;
  это не свидетельство нового harness run на изменённых документах.

Среда: Linux/Arch x86_64, CPython 3.14.7-1, SuperCollider 3.14.1-6
(`sclang`/`scsynth` 3.14.1), libsndfile 1.2.2-4, bubblewrap 0.12.0-1,
локальная POSIX FS с hard links. Это одна проверенная среда, не расширение
поддержки. Происхождение/ограниченная security-проверка описаны в
[compatibility](../../../skills/supercollider/references/compatibility.md).

## Исполняемые проверки

Из корня указанной ревизии, с установленными зависимостями:

```sh
python3 -B -m unittest discover -s tests/unit -v
python3 -B -m unittest discover -s tests/contract -v
```

Результат: **29 unit + 29 contract PASS**. На том же implementation/package
snapshot ранее выполнены **13 real integration PASS**, без skip, через
документированный clean environment и gated bwrap runner:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  HOME=/owned/check/home XDG_CONFIG_HOME=/owned/check/config \
  XDG_DATA_HOME=/owned/check/data XDG_CACHE_HOME=/owned/check/cache \
  XDG_RUNTIME_DIR=/owned/check/runtime TMPDIR=/owned/check/tmp \
  SCS_EVIDENCE_DIR=/owned/check/evidence SCS_REAL_TESTS=1 \
  python3 -B -m unittest discover -s tests/integration -v
```

Все `/owned/check/` каталоги предварительно создаёт вызывающий в своей области.
До opt-in подтверждаются namespace/headless условия, не предполагаются.
Команда выше — повторяемая процедура, не разрешение запускать её или ставить
зависимости. В docs-only дополнении **29 unit + 29 contract повторены: PASS**,
exit 0; `git diff --check`, local Markdown links и сверка фактов с retained
smoke evidence — PASS. В публикуемые документы не включены raw sessions,
credentials, private config или локальные абсолютные пути. Native suite
не повторяется, поскольку её runtime/test/fixture bytes не изменены.

| Критерии | Наблюдаемые случаи и пределы |
|---|---|
| AC-001/008/015 | Настоящие малые NRT renders без GUI/audio/network/realtime state, полное WAV-декодирование; frames/rate/channels exact. Неверные свойства — отказ. |
| AC-002–005 | Невалидные source/Score/declarations, missing SynthDef/resource/dependency, syntax/runtime/server/wrapper errors не становятся success; применимые native случаи дополняют controlled boundary models. |
| AC-006/012 | Deadlines, SIGINT/SIGTERM, owned descendants/reap, чужой контроль жив; stage fault injection — contract model, не kernel certification/SIGKILL guarantee. |
| AC-007/013/014 | Missing/broken/truncated WAV, недостаточное resource evidence, JSON/status/exit agreement, partial/published-not-ready и unfinished actions. |
| AC-009–011 | Absolute/relative/metachar paths, защищённые aliases, no-replace и competing publishers. Process/FS реальные; concurrent SC fault certification не заявлена. |
| AC-016 | Native load + один explicit-activation minimal scenario ниже. Static checks его не заменяют. |
| AC-017 | Small fixed-seed repeat: RMSE 0 ≤2/32768, RMS difference 0 ≤1e−4; resource initial float32 equality. Реальный 1000s/192k render **NOT RUN / UNVERIFIED**; только pure model 192000128 frames PASS. |
| AC-018 | Code/static audit и readonly-host/owned-write test runner; нет install/update/remove/global-config операций render. Не hostile-source sandbox и не полный CVE audit. |

## Один согласованный native harness smoke: AC-016

Установленный **OpenCode v2.0.32**; V2 CLI/skills/config документация и локальные
`opencode --version`, `opencode run --help` прочитаны перед запуском.
Штатный build agent, CLI default **opencode/minimax-m3.1-flash-free**,
без `--model` и без смены модели (проверено по assistant messages export).
Согласован один запуск до 300 секунд, один nominal 2s render, без installs и
system/global config изменений. **50.175384649 seconds, harness exit 0**.

### Процедура воспроизведения без приватных данных

1. Получить идентифицированную implementation revision выше; скопировать только
   полную `skills/supercollider/` в свежий test-dir под
   `.opencode/skills/supercollider/`. Не копировать RIS, остальные навыки,
   пользовательские AGENTS/config/credentials или музыкальные интеграции.
2. Использовать уже настроенный совместимый harness/provider. В тестовом local
   config отключить snapshots, разрешить native skill `supercollider` и чтение;
   исполнение разрешить только через evidence isolation prefix. Прочие изменения,
   сеть через инструменты, новые renders и системные действия запретить.
   Это описание тестовой политики, не изменение глобальной конфигурации.
3. Создать свежий caller-owned output-dir и private HOME/XDG/TMP под ним.
   Evidence-only prefix проверяет один согласованный argv, хранит one-shot marker,
   запускает bwrap с `--die-with-parent --unshare-net --unshare-pid`,
   `--ro-bind / / --proc /proc --dev /dev --dir /dev/snd`, writable bind только
   output-dir. Очистить окружение до PATH, LANG, private HOME/XDG/TMP и
   `QT_QPA_PLATFORM=offscreen`. До exec CLI в том же namespace подтвердить
   distinct net/PID, только loopback/no external route, отсутствие GUI vars,
   аудиоустройств и realtime SC. Prefix не строит/не исправляет CLI argv.
4. Один ограниченный внешним timeout запуск из test-dir:

   ```sh
   opencode run --standalone --format json --print-logs --log-level debug \
     --title 'nrt-render AC-016 one-shot smoke' '<bounded prompt>'
   ```

   Prompt: явно потребовать **native `skill({"id":"supercollider"})`**, затем
   чтение обязательных references/fixture и один render штатным CLI через prefix.
   Вход — packaged `assets/minimal-nrt.scd`; новый output `result.wav`;
   duration 2, rate 48000, channels 2, seed 0, timeout 60; diagnostics/temp base —
   созданный output-dir. Запретить retry, edits, installs, realtime/GUI/playback,
   другие skills и сетевые tools. Агент должен сам составить documented argv
   и вернуть parsed schema2 result, ready/partial, expected/measured, diagnostics.
   Общий deadline включал termination: 295s wait + до5s TERM/KILL.
5. Сохранить JSONL native tool events, exit, argv/clean child env, namespace
   witness, SC diagnostic streams/manifests и WAV в своей области. Проверить
   реальный completed skill load, subsequent agent shell и ровно один render;
   export сессии позволяет установить actual model без нового LLM turn.
   Не публиковать raw session/config/credentials: этого compact report достаточно
   для фиксации фактов, а повтор создаёт новые локальные свидетельства.
6. Независимо открыть WAV stdlib `wave`, прочитать **весь** payload и проверить
   `(channels,width,rate,frames) == (2,2,48000,96064)`, bytes == 384256;
   decoded PCM16 sound window 0.1–1.9s: RMS 0.1/√2 ±0.002,
   sine/cosine 480Hz projection amplitude 0.1 ±0.002.

Этот smoke **был выполнен**, не только предложен: native tool completed для
`supercollider`, агент прочитал три references и fixture, выполнил один shell
render через prefix, CLI success/complete/0, один verified/published ready,
без partial/errors/unfinished actions. Никакие OpenCode-only hooks, RIS, music
или Remotion не участвовали. Ordinary model-provider network разрешена;
отсутствие сети утверждается только для SC subtree, не для LLM.

### Измерения и честные пределы

- Независимый full decode: PCM16 stereo, 48000 Hz, **96064 frames**, 192128
  samples, 384256 PCM bytes; nominal 2s, expected/measured 2.001333333333333s.
- Оба канала: RMS **0.07070787417269793**, amplitude 480Hz
  **0.09999603148310965**. Допуски соблюдены; тишина/клиппинг/музыкальная оценка
  публичным success criterion не становятся.
- SHA-256 **WAV file**:
  `eb803d72c59dea95c8dd4b11bb2f7f5ec735f4768d73de4ec3acb68dfdeef552`.
- SHA-256 **decoded PCM bytes**:
  `d0c3d295066a8c234c0a3d6d2be1adc397fd30863536efd3ab34231ec21f03e5`.
  Test-agent prose ошибочно назвал первый hash PCM hash; это исправлено
  независимым чтением, не повторным render и не доверием ответу модели.
- Четыре известных nonfatal scheduling-priority warnings сохранены;
  неожиданные существенные ошибки не игнорируются.
- Три лишних `ls` agent attempts отклонены permissions, не выполнились.
  Render retry не было. Это **не** доказательство идеального соблюдения
  инструкций, автономной маршрутизации, повторяемой agent reliability,
  стоимости будущих запусков или поддержки других harnesses/models/platforms.
- После запуска host scsynth/supernova отсутствовали; чужие процессы не
  завершались. Runtime source остаётся доверенным executable, не sandbox.

## Точка остановки

AC-016 имеет положительное наблюдение для одного явно активированного сценария.
Общий feature acceptance/closure не заявлен: long-render limitation сохранён,
новое evidence/docs/rules change требует независимого combined review.
README и compatibility согласованы с этим отчётом; accepted spec/design/decisions
не редактировались. Git-публикация, tracker completion и Dolt-публикация — разные
результаты; в этом docs-only продолжении ни один не выполнялся.
