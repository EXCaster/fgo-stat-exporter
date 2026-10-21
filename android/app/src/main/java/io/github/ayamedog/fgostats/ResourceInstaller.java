package io.github.ayamedog.fgostats;

import android.content.Context;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;

/** 公开资源按构建清单逐个校验，禁止从压缩包写入其他路径。 */
final class ResourceInstaller {
    private ResourceInstaller() {}

    static File prepare(Context context) throws Exception {
        JSONObject expected;
        try (InputStream input = context.getAssets().open("public-manifest.json")) {
            expected = new JSONObject(new String(readBounded(input, 512 * 1024), StandardCharsets.UTF_8));
        }
        File root = new File(context.getFilesDir(), "public-resources");
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("RESOURCE_DIRECTORY_FAILED");
        Set<String> seen = new HashSet<>();
        long total = 0;
        try (ZipInputStream input = new ZipInputStream(context.getAssets().open("public-resources.zip"))) {
            ZipEntry item;
            byte[] buffer = new byte[65536];
            while ((item = input.getNextEntry()) != null) {
                String name = item.getName();
                if (item.isDirectory() || !expected.has(name) || !seen.add(name))
                    throw new IOException("RESOURCE_SET_INVALID");
                File target = new File(root, name);
                if (!target.getCanonicalPath().startsWith(root.getCanonicalPath() + File.separator))
                    throw new IOException("RESOURCE_PATH_INVALID");
                String wanted = expected.getString(name);
                boolean reuse = target.isFile() && digest(target).equals(wanted);
                if (!target.getParentFile().isDirectory() && !target.getParentFile().mkdirs())
                    throw new IOException("RESOURCE_DIRECTORY_FAILED");
                File partial = new File(target.getPath() + ".partial");
                MessageDigest hash = MessageDigest.getInstance("SHA-256");
                try (OutputStream output = reuse ? new ByteArrayOutputStream(0) : new FileOutputStream(partial)) {
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        total += count;
                        if (total > 200L * 1024 * 1024) throw new IOException("RESOURCE_LIMIT");
                        hash.update(buffer, 0, count);
                        if (!reuse) output.write(buffer, 0, count);
                    }
                }
                if (!hex(hash.digest()).equals(wanted)) {
                    if (partial.exists()) partial.delete();
                    throw new IOException("RESOURCE_HASH_INVALID");
                }
                if (!reuse && !partial.renameTo(target)) throw new IOException("RESOURCE_WRITE_FAILED");
            }
        }
        if (seen.size() != expected.length()) throw new IOException("RESOURCE_SET_INVALID");
        return root;
    }

    static byte[] readBounded(InputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[65536];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (output.size() + count > limit) throw new IOException("INPUT_TOO_LARGE");
            output.write(buffer, 0, count);
        }
        return output.toByteArray();
    }

    private static String digest(File file) throws Exception {
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) hash.update(buffer, 0, count);
        }
        return hex(hash.digest());
    }

    private static String hex(byte[] raw) {
        StringBuilder text = new StringBuilder();
        for (byte value : raw) text.append(String.format(Locale.ROOT, "%02x", value & 255));
        return text.toString();
    }
}
