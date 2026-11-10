# {{SLUG}}

| field | value |
|---|---|
| artifact | `{{FILE}}` |
| sha256 | `{{SHA256}}` |
| opened | {{DATE}} |
| package / versionCode | _from evidence/{{SLUG}}/resources.json_ |
| signing schemes | _from evidence/{{SLUG}}/signature.json_ |
| framework | _dex / Flutter / IL2CPP / React Native / Cordova_ |
| status | open |

Every claim below cites the evidence file and the exact REA operation that
produced it. A claim with no citation is a guess and is marked as one.

## 1. What was asked

_The behaviour under study, in one sentence (e.g. "how does the search box
rank results", "what does this screen send on submit")._

## 2. Surface

| layer | where | evidence |
|---|---|---|
| manifest | `AndroidManifest.xml` | `evidence/{{SLUG}}/resources.json` |
| dex | `classes*.dex` | |
| native | `lib/arm64-v8a/*.so` | |
| assets | | |

## 3. Data flow

What goes in, what comes out, and what the app records about it. Each row
needs a concrete location, not just a name.

| kind | symbol / key | location | note |
|---|---|---|---|
| input | | | |
| transform | | | |
| network / telemetry | | | |

## 4. The code

Native findings go in an asm window: one line per instruction, its effect
stated on the same line. Addresses are file-relative unless an image base is
named; resolve them with `rea address-to-file-offset` and say which you used.
The example below reads a small UTF-8 length-prefix helper — replace it with
the routine you are documenting.

```asm
; lib/arm64-v8a/libexample.so  .text  (base 0x0 = file offset)
; AOB: FF 43 00 D1 F3 53 01 A9          ; mask: xx xx xx xx xx xx xx xx
0x0000C210  SUB   SP, SP, #0x10         ; open a 16-byte frame
0x0000C214  STP   X19, X20, [SP]        ; save two callee-saved registers
0x0000C218  LDRB  W8, [X0]             ; W8 = first byte of the buffer = length
0x0000C21C  ADD   X19, X0, #1          ; X19 -> payload (one past the length byte)
0x0000C220  MOV   X20, X8             ; keep the length for the copy loop
0x0000C224  BL    #0x0000D080          ; -> utf8_validate(payload, len)
0x0000C228  LDP   X19, X20, [SP]       ; restore saved registers
0x0000C22C  ADD   SP, SP, #0x10        ; close the frame
0x0000C230  RET                        ; return W0 = validated length
```

In-world effect: _what this routine causes the app to show or do, quoting the
address and the AOB so the same bytes can be re-found in a later build._

## 5. Evidence index

| file | operation | what it establishes |
|---|---|---|
| `evidence/{{SLUG}}/signature.json` | `inspect-apk-signature` | signer identity, digests |
| `evidence/{{SLUG}}/resources.json` | `decode-android-resources` | package, components, strings |
| | | |

## 6. Open questions

_What is still unproven, and the next REA operation that would settle it._
