# waydroid-libmoai-ashmem-fix

Fix **微信读书 / WeRead** (`com.tencent.weread`, `com.tencent.weread.eink`) crashing on
startup inside **Waydroid**, and its offline book downloads failing, on hosts whose
kernel has no `ashmem` (every kernel ≥ 5.18, i.e. basically all current desktop kernels).

> **TL;DR** — WeRead ships its own `ashmem_set_prot_region()` inside
> `libmoai-sqlite.so`. It issues the legacy `ioctl(ASHMEM_SET_PROT_MASK)` without
> checking whether the fd is really ashmem. Waydroid emulates ashmem with `memfd`
> (correctly, and it already does this — `sys.use_memfd=true`), and `memfd` rejects
> that ioctl with `ENOTTY`, so `CursorWindow` creation fails and the app dies before
> `Application.onCreate` finishes. Patch that one function to `return 0`.

```
ioctl(76, _IOC(_IOC_WRITE, 0x77, 0x5, 0x4) /* ASHMEM_SET_PROT_MASK */, 0x3) = -1 ENOTTY
```

Applies to any app carrying the Tencent *moai* SQLite stack, not only WeRead.

---

## Symptom

```
java.lang.RuntimeException: Unable to create application com.tencent.weread.WRApplication:
  CursorWindowAllocationException: Cursor window allocation of 2048 kb failed.
    at com.tencent.moai.database.sqlite.CursorWindow.create(...)
    at moai.storage.Cache$CacheWrapper.optional(...)
    at com.tencent.weread.account.AppSettingManager.getCurrentLoginAccountId(...)
```

Process starts, runs 80–1500 ms, then dies. `data/system/dropbox/data_app_crash@*.txt`
holds the same stack every time.

## Root cause

`strace` of the app process (full excerpt in `evidence/`):

```
memfd_create("CursorWindow: /data/user/0/com.t"..., MFD_CLOEXEC|MFD_ALLOW_SEALING) = 76  OK
ftruncate64(76, 2097152)                                   = 0                           OK
fcntl64(76, F_ADD_SEALS, F_SEAL_SHRINK|F_SEAL_GROW)        = 0                           OK
ioctl(76, _IOC(_IOC_WRITE, 0x77, 0x5, 0x4), 0x3)           = -1 ENOTTY                  FAIL
close(76);  →  "Could not allocate CursorWindow ... due to error -1"
```

1. Waydroid's memfd emulation **is working** (all of create/ftruncate/seal succeed).
   Re-running `waydroid init`, editing props or upgrading Waydroid changes nothing.
2. The failure is the *legacy* ashmem ioctl **after** the memfd was created: a memfd is
   not an ashmem char device, so `ASHMEM_SET_PROT_MASK` is `ENOTTY`.
3. The *system* is fine: `system/lib64/libcutils.so`'s `ashmem_set_prot_region()` is
   memfd-aware (it calls `ashmem_valid(fd)` first and uses `fcntl` for memfds), which is
   why system apps work.
4. The app brings its own implementation, which is not memfd-aware:

   ```
   readelf -W --dyn-syms lib/armeabi-v7a/libmoai-sqlite.so
     ashmem_create_region    size=4    (thunk → libcutils, memfd path, fine)
     ashmem_set_prot_region  size=56   (raw ioctl, no fd check)
   ```
5. Why it works on phones: `drivers/staging/android/ashmem.c` was only removed from
   mainline in **Linux 5.18** (`721412ed`). Android 13-era devices run 5.10/5.15 GKI
   kernels where `/dev/ashmem` is real, so the ioctl succeeds.
6. Upstream Waydroid issue for this exact crash is still open:
   <https://github.com/waydroid/waydroid/issues/2080>

## The patch

Overwrite the first instructions of `ashmem_set_prot_region()` so it returns 0:

| ABI | sym vaddr | file offset | original | patched | disasm |
|---|---|---|---|---|---|
| arm64-v8a | `0x222c4` | `0x222c4` | `f5 0f 1d f8 f4 4f 01 a9` | `00 00 80 52 c0 03 5f d6` | `mov w0,#0 ; ret` |
| armeabi-v7a | `0x155ed` (Thumb) | `0x155ec` | `f0 b5 03 af` | `00 20 70 47` | `movs r0,#0 ; bx lr` |

(Offsets are for WeRead 10.2.2 / ink 2.1.2; `patch_so.py` resolves them from the
symbol table, so other versions work too.)

This is safe for `CursorWindow`: the only call is "make this region read+write", which a
memfd already allows. The other `ashmem_*` helpers are not reimplemented by that library,
so they use libcutils' memfd-aware versions and need no change.

## Usage (recommended: patch the installed copy)

Keeping the APK untouched means the **original Tencent signature stays valid**, which
matters: a re-signed build cannot download offline books
(`ao.ZipException: Wrong password!`) and breaks WeChat-SDK login.

```bash
# 1. install the untouched APK
waydroid app install /path/to/weread.apk

# 2. patch the native library that Waydroid extracted
./patch-installed.sh com.tencent.weread
./patch-installed.sh com.tencent.weread.eink   # if you use the e-ink build

# 3. (re)start the app
waydroid app launch com.tencent.weread
```

`patch-installed.sh` is idempotent. **Re-run it after every app update / reinstall.**

It edits `~/.local/share/waydroid/data/app/~~*/<pkg>-*/lib/<abi>/libmoai-sqlite.so`.

## Alternative: patch + re-sign the APK (not recommended)

Works for starting the app, but downloads of offline books fail afterwards because the
book container is decrypted with a key tied to the original signature, and WeChat login
(standard build) will likely reject the re-signed app.

```bash
cd /tmp && rm -rf rp && mkdir rp && cd rp
unzip -o /path/to/weread_ink.apk 'lib/*/libmoai-sqlite.so' -d x
python3 /path/to/tools/patch_so.py x/lib/*/libmoai-sqlite.so
python3 /path/to/tools/repack.py /path/to/weread_ink.apk unsigned.apk \
  "lib/arm64-v8a/libmoai-sqlite.so=x/lib/arm64-v8a/libmoai-sqlite.so" \
  "lib/armeabi-v7a/libmoai-sqlite.so=x/lib/armeabi-v7a/libmoai-sqlite.so"

# use the apksigner/zipalign from your Android SDK build-tools
keytool -genkeypair -keystore my.keystore -alias k -keyalg RSA -keysize 2048 \
        -validity 10000 -storepass mypass -keypass mypass -dname "CN=local"
zipalign -p -f 4 unsigned.apk aligned.apk
apksigner sign --ks my.keystore --ks-pass pass:mypass --key-pass pass:mypass \
        --out signed.apk aligned.apk
waydroid app install signed.apk
```

## Files

```
patch-installed.sh     patch the already-installed app (recommended path)
tools/patch_so.py      ELF helper: find a symbol, map vaddr→file offset, write a
                       return-0 stub (AArch64 / ARM / Thumb), arch auto-detected
tools/repack.py        rewrite an APK replacing some entries, preserving compression
                       method, order and attributes
evidence/              strace excerpt, ioctl decoding, dropbox stack, conclusions
```

## Notes / things that do NOT help

- `waydroid init -f`, editing `waydroid.prop`, upgrading Waydroid — memfd mode is
  already active and correct
- Installing the 32-bit ABI (`pm install --abi armeabi-v7a`) — crashes identically
- Trying another app version — both the e-ink and the standard build ship the same
  `libmoai-sqlite.so` code path
- Adding an in-tree ashmem driver to the kernel *would* fix it (a port of the removed
  `drivers/staging/android/ashmem.c` to the 7.x VMA API needs `vm_flags_clear()`,
  `legacy_to_vma_flags()`, `shrinker_alloc/register/free`, and must be `=y` because
  `shmem_zero_setup()` is not exported), but patching one function in one library is a
  much smaller change

## License

Scripts and documentation: MIT. No Tencent binaries are redistributed here — you patch
the APK you already own.
