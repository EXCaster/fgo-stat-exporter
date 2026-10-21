package io.github.ayamedog.fgostats;

import android.content.ContentValues;
import android.content.Context;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

/** 只向系统相册写入本次生成的图片，不读取已有照片。 */
final class GalleryWriter {
    private GalleryWriter() { }

    @SuppressWarnings("deprecation")
    static void save(Context context, byte[] bytes, String suggestedName) throws IOException {
        String time = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
        String name = suggestedName.substring(0, suggestedName.length() - 4) + "-" + time
            + "-" + UUID.randomUUID().toString().substring(0, 8) + ".jpg";
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
        values.put(MediaStore.Images.Media.DATE_TAKEN, System.currentTimeMillis());
        File legacyFile = null;
        Uri item = null;
        boolean completed = false, legacyCreated = false;
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/FGO抓包统计");
                values.put(MediaStore.Images.Media.IS_PENDING, 1);
            } else {
                File pictures = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES).getCanonicalFile();
                File album = new File(pictures, "FGO抓包统计").getCanonicalFile();
                if (!album.getParentFile().equals(pictures) || (!album.isDirectory() && !album.mkdirs()))
                    throw new IOException();
                legacyFile = new File(album, name);
                if (!legacyFile.getCanonicalFile().getParentFile().equals(album))
                    throw new IOException();
                if (!legacyFile.createNewFile()) throw new IOException();
                legacyCreated = true;
                values.put(MediaStore.Images.Media.DATA, legacyFile.getPath());
            }
            Uri collection = Build.VERSION.SDK_INT >= 29
                ? MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                : MediaStore.Images.Media.EXTERNAL_CONTENT_URI;
            item = context.getContentResolver().insert(collection, values);
            if (item == null) throw new IOException();
            try (OutputStream output = context.getContentResolver().openOutputStream(item, "w")) {
                if (output == null) throw new IOException();
                output.write(bytes);
                output.flush();
            }
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues ready = new ContentValues();
                ready.put(MediaStore.Images.Media.IS_PENDING, 0);
                if (context.getContentResolver().update(item, ready, null, null) != 1)
                    throw new IOException();
            } else {
                MediaScannerConnection.scanFile(context, new String[] {legacyFile.getPath()}, new String[] {"image/jpeg"}, null);
            }
            completed = true;
        } finally {
            if (!completed) {
                // 失败时只清理由本次保存创建的空记录和文件，不覆盖已有照片。
                if (item != null) {
                    try { context.getContentResolver().delete(item, null, null); }
                    catch (RuntimeException ignored) { }
                }
                if (legacyCreated) legacyFile.delete();
            }
        }
    }
}
