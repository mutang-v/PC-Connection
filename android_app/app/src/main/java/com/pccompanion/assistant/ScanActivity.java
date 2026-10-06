package com.pccompanion.assistant;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.Camera;
import android.os.Build;
import android.os.Bundle;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.TextView;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;

/**
 * 相机扫码 Activity：用旧版 Camera API（兼容 Android 8 / P9）+ ZXing core
 * 就地解码二维码，用于"扫码配对"。
 *
 * 返回格式：RESULT_PAYLOAD = "host=..&code=.." 或空（未识别）。
 */
public class ScanActivity extends Activity implements SurfaceHolder.Callback, Camera.PreviewCallback {

    public static final String RESULT_PAYLOAD = "pair_payload";

    private static final String QR_PREFIX = "PCCONN:1|";
    private static final long DECODE_INTERVAL_MS = 450; // 两次解码采样间隔，降低功耗

    private Camera camera;
    private SurfaceView preview;
    private TextView tvHint;
    private MultiFormatReader reader;
    private boolean activityVisible = false;
    private long lastDecodeTime = 0;
    private boolean finishing = false;
    private boolean failed = false;

    private static final int REQ_CAMERA = 100;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.layout_scan);

        preview = findViewById(R.id.preview);
        tvHint = findViewById(R.id.tvHintPhoneScan);

        Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
        hints.put(DecodeHintType.POSSIBLE_FORMATS, Collections.singletonList(
                com.google.zxing.BarcodeFormat.QR_CODE));
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
        reader = new MultiFormatReader();
        reader.setHints(hints);

        SurfaceHolder holder = preview.getHolder();
        holder.addCallback(this);
        holder.setType(SurfaceHolder.SURFACE_TYPE_PUSH_BUFFERS);
        tvHint.setText("将电脑屏幕上的配对二维码对准取景框");
    }

    private void checkCameraPermissionAndOpen() {
        if (Build.VERSION.SDK_INT >= 23) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                return;
            }
        }
        openCamera();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_CAMERA) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                openCamera();
            } else {
                failed = true;
                tvHint.setText("未授予相机权限，无法扫码配对");
            }
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        activityVisible = true;
        if (camera == null && !failed) checkCameraPermissionAndOpen();
    }

    @Override
    protected void onPause() {
        super.onPause();
        activityVisible = false;
        releaseCamera();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        releaseCamera();
    }

    private void openCamera() {
        try {
            camera = Camera.open();
            camera.setPreviewCallback(this);
            startPreviewIfReady();
        } catch (Exception e) {
            failed = true;
            tvHint.setText("无法打开相机：" + e.getMessage());
        }
    }

    private void startPreviewIfReady() {
        if (camera == null) return;
        SurfaceHolder h = preview.getHolder();
        if (h.getSurface().isValid()) {
            try {
                camera.setPreviewDisplay(h);
                camera.setPreviewCallback(this);
                camera.startPreview();
            } catch (Exception ignored) { /* 稍后由 surfaceChanged 重试 */ }
        }
    }

    private void releaseCamera() {
        if (camera != null) {
            try { camera.setPreviewCallback(null); } catch (Exception ignored) {}
            try { camera.stopPreview(); } catch (Exception ignored) {}
            camera.release();
            camera = null;
        }
    }

    // ---- SurfaceHolder.Callback ----
    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        startPreviewIfReady();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        startPreviewIfReady();
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        releaseCamera();
    }

    // ---- Camera.PreviewCallback：每帧 YUV(NV21) 数据 ----
    @Override
    public void onPreviewFrame(byte[] data, Camera camera) {
        if (finishing || !activityVisible || data == null || reader == null) return;
        long now = System.currentTimeMillis();
        if (now - lastDecodeTime < DECODE_INTERVAL_MS) return;
        lastDecodeTime = now;

        Camera.Parameters params = camera.getParameters();
        if (params == null) return;
        Camera.Size size = params.getPreviewSize();
        if (size == null) return;
        int w = size.width;
        int h = size.height;
        if (w <= 0 || h <= 0) return;

        try {
            byte[] gray = yuvToGray(data, w, h);
            int cropW = w;
            int cropH = h;
            PlanarYUVLuminanceSource src = new PlanarYUVLuminanceSource(
                    gray, w, h, 0, 0, cropW, cropH, false);
            Result r = reader.decodeWithState(new BinaryBitmap(new HybridBinarizer(src)));
            if (r != null) handleResult(r.getText());
        } catch (Exception ignored) {
            // 未识别到二维码，等待下一帧
        } finally {
            try { reader.reset(); } catch (Exception ignored) {}
        }
    }

    /** NV21 YUV -> 灰度 byte[]（取 Y 分量）。 */
    private byte[] yuvToGray(byte[] nv21, int width, int height) {
        int frameSize = width * height;
        byte[] out = new byte[frameSize];
        System.arraycopy(nv21, 0, out, 0, frameSize);
        return out;
    }

    private void handleResult(String text) {
        if (text == null || !text.startsWith(QR_PREFIX)) return;
        String payload = text.substring(QR_PREFIX.length());
        finishing = true;
        releaseCamera();
        Intent res = new Intent();
        res.putExtra(RESULT_PAYLOAD, payload);
        setResult(RESULT_OK, res);
        finish();
    }
}
