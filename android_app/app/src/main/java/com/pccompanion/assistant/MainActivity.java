package com.pccompanion.assistant;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    private static final String PREFS = "pc_companion";
    private static final String KEY_HOST = "host";
    private static final String KEY_TOKEN = "token";
    private static final int C_GREEN = Color.rgb(71, 225, 161);
    private static final int C_RED = Color.rgb(255, 102, 127);
    private static final int C_MUTED = Color.rgb(140, 162, 196);
    private static final int C_ORANGE = Color.rgb(255, 189, 105);
    private static final int C_BLUE = Color.rgb(79, 140, 255);

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newFixedThreadPool(3);

    private SharedPreferences prefs;
    private String host = "";
    private String token = "";

    private FrameLayout contentFrame;
    private View pairingView;
    private View monitorView;
    private View toolsView;

    private TextView tvStatus, tvHostLabel, tvUpdated;
    private EditText etHost, etCode;
    private TextView tvPairErr;

    private Button tabMonitor, tabTools;

    // 趋势图 / 采样状态
    private final java.util.Deque<Double> cpuTrend = new java.util.ArrayDeque<>();
    private final java.util.Deque<Double> memTrend = new java.util.ArrayDeque<>();
    private boolean showMemTrend = false;
    private static final int TREND_MAX = 24;
    // CPU 采样基线（两次调用才能算出真实使用率）
    private boolean cpuBaseReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        host = prefs.getString(KEY_HOST, "");
        token = prefs.getString(KEY_TOKEN, "");

        contentFrame = findViewById(R.id.contentFrame);
        tvStatus = findViewById(R.id.tvStatus);
        tvHostLabel = findViewById(R.id.tvHostLabel);
        tabMonitor = findViewById(R.id.tabMonitor);
        tabTools = findViewById(R.id.tabTools);

        pairingView = getLayoutInflater().inflate(R.layout.layout_pairing, contentFrame, false);
        monitorView = getLayoutInflater().inflate(R.layout.layout_monitor, contentFrame, false);
        toolsView = getLayoutInflater().inflate(R.layout.layout_tools, contentFrame, false);

        etHost = pairingView.findViewById(R.id.etHost);
        etCode = pairingView.findViewById(R.id.etCode);
        tvPairErr = pairingView.findViewById(R.id.tvPairErr);
        Button btnPair = pairingView.findViewById(R.id.btnPair);
        btnPair.setOnClickListener(v -> doPair());
        Button btnScan = pairingView.findViewById(R.id.btnScan);
        btnScan.setOnClickListener(v -> startScan());

        tabMonitor.setOnClickListener(v -> showPage("monitor"));
        tabTools.setOnClickListener(v -> showPage("tools"));

        // 监控页：趋势图切换
        View trendBox = monitorView.findViewById(R.id.trendCanvas);
        if (trendBox != null) trendBox.setOnClickListener(v -> {
            showMemTrend = !showMemTrend;
            renderTrend();
        });

        // 工具页
        toolsView.findViewById(R.id.btnOptimize).setOnClickListener(v -> doOptimize());
        toolsView.findViewById(R.id.btnProcesses).setOnClickListener(v -> loadProcesses());
        toolsView.findViewById(R.id.btnTaskManager).setOnClickListener(v -> quickAction("task_manager"));
        toolsView.findViewById(R.id.btnNetworkSettings).setOnClickListener(v -> quickAction("network_settings"));
        toolsView.findViewById(R.id.btnWindowsSettings).setOnClickListener(v -> quickAction("windows_settings"));
        toolsView.findViewById(R.id.btnSleep).setOnClickListener(v -> confirmPower("system_sleep", "睡眠"));
        toolsView.findViewById(R.id.btnRestart).setOnClickListener(v -> confirmPower("system_restart", "重启"));
        toolsView.findViewById(R.id.btnShutdown).setOnClickListener(v -> confirmPower("system_shutdown", "关机"));

        // 工具页：媒体 & 音量
        toolsView.findViewById(R.id.btnMediaPrev).setOnClickListener(v -> quickAction("media_prev"));
        toolsView.findViewById(R.id.btnMediaPlay).setOnClickListener(v -> quickAction("media_play_pause"));
        toolsView.findViewById(R.id.btnMediaNext).setOnClickListener(v -> quickAction("media_next"));
        toolsView.findViewById(R.id.btnVolDown).setOnClickListener(v -> doVolumeDelta(-10));
        toolsView.findViewById(R.id.btnVolUp).setOnClickListener(v -> doVolumeDelta(10));
        toolsView.findViewById(R.id.btnVolMute).setOnClickListener(v -> quickAction("volume_mute"));
        SeekBar volSeek = toolsView.findViewById(R.id.volSeek);
        volSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar sb, int progress, boolean fromUser) {
                if (fromUser) {
                    setText(toolsView, R.id.tvVolPct, progress + "%");
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                doSetVolume(seekBar.getProgress());
            }
        });
        // 工具页：剪贴板
        toolsView.findViewById(R.id.btnClipRead).setOnClickListener(v -> readClipboard());
        toolsView.findViewById(R.id.btnClipWrite).setOnClickListener(v -> writeClipboard());
        // 工具页：通知
        toolsView.findViewById(R.id.btnNotify).setOnClickListener(v -> sendNotify());
        // 工具页：重新连接 / 重新配对
        toolsView.findViewById(R.id.btnReconnect).setOnClickListener(v -> doReconnect());

        if (token.isEmpty()) {
            showPage("pair");
        } else {
            showPage("monitor");
        }
    }

    private void showPage(String page) {
        contentFrame.removeAllViews();
        if (page.equals("pair")) {
            contentFrame.addView(pairingView, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            styleTabs(false, false);
            tvStatus.setText("● 等待配对");
            tvStatus.setTextColor(C_MUTED);
            return;
        }
        View target;
        if (page.equals("monitor")) {
            target = monitorView;
            styleTabs(true, false);
        } else {
            target = toolsView;
            styleTabs(false, true);
            refreshTools();
        }
        contentFrame.addView(target, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        startClock();
    }

    private void styleTabs(boolean m, boolean t) {
        tabMonitor.setBackgroundResource(m ? R.drawable.tab_active : R.drawable.tab_inactive);
        tabMonitor.setTextColor(m ? color(R.color.text_primary) : color(R.color.text_muted));
        tabTools.setBackgroundResource(t ? R.drawable.tab_active : R.drawable.tab_inactive);
        tabTools.setTextColor(t ? color(R.color.text_primary) : color(R.color.text_muted));
    }

    private int color(int colorRes) {
        return getResources().getColor(colorRes);
    }

    private void startClock() {
        ui.removeCallbacks(clockTick);
        ui.post(clockTick);
        ui.removeCallbacks(ticker);
        ui.postDelayed(ticker, 300);
    }

    private final Runnable clockTick = new Runnable() {
        @Override
        public void run() {
            TextView tv = findViewById(R.id.tvClock);
            if (tv != null) tv.setText(java.text.DateFormat.getTimeInstance(java.text.DateFormat.MEDIUM).format(new java.util.Date()));
            ui.postDelayed(this, 1000);
        }
    };

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (contentFrame != null && contentFrame.indexOfChild(monitorView) >= 0) {
                refreshStats();
            }
            ui.postDelayed(this, 2500);
        }
    };

    // ============ 扫码配对 ============

    private void startScan() {
        try {
            startActivityForResult(new Intent(this, ScanActivity.class), REQ_SCAN);
        } catch (Exception e) {
            toast("无法启动扫码：" + e.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SCAN && resultCode == RESULT_OK && data != null) {
            String payload = data.getStringExtra(ScanActivity.RESULT_PAYLOAD);
            if (payload == null || payload.isEmpty()) {
                tvPairErr.setText("未识别到配对信息");
                return;
            }
            // payload 格式：host=..&code=..
            String hostPart = null, codePart = null;
            for (String kv : payload.split("&")) {
                int idx = kv.indexOf('=');
                if (idx < 0) continue;
                String k = kv.substring(0, idx);
                String v = kv.substring(idx + 1);
                if (k.equals("host")) hostPart = v;
                else if (k.equals("code")) codePart = v;
            }
            if (hostPart == null || hostPart.isEmpty() || codePart == null || codePart.isEmpty()) {
                tvPairErr.setText("二维码内容不完整，请手动输入");
                return;
            }
            etHost.setText(hostPart);
            etCode.setText(codePart);
            doPair(); // 自动触发配对
        }
    }

    private void doPair() {
        String h = etHost.getText().toString().trim();
        String code = etCode.getText().toString().trim();
        if (h.isEmpty()) {
            tvPairErr.setText("请输入电脑 IP 或主机名");
            return;
        }
        hideKeyboard();
        tvPairErr.setText("");
        host = h;
        io.execute(() -> {
            try {
                JSONObject res = apiPost("/api/pair", "{\"code\":\"" + code + "\"}", false);
                boolean ok = res.optBoolean("ok", false);
                String msg = res.optString("message", "配对失败");
                if (ok && res.has("token")) {
                    String t = res.getString("token");
                    prefs.edit().putString(KEY_HOST, h).putString(KEY_TOKEN, t).apply();
                    token = t;
                    ui.post(() -> { showPage("monitor"); toast("设备配对成功"); });
                } else {
                    ui.post(() -> tvPairErr.setText(msg));
                }
            } catch (Exception e) {
                ui.post(() -> tvPairErr.setText("无法连接：".concat(String.valueOf(e.getMessage()))));
            }
        });
    }

    private void doReconnect() {
        // 清除本地保存的连接信息，回到配对页重新连接
        prefs.edit().remove(KEY_HOST).remove(KEY_TOKEN).apply();
        host = "";
        token = "";
        ui.post(() -> { showPage("pair"); toast("已清除连接，请重新配对"); });
    }

    private void refreshStats() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/stats");
                ui.post(() -> renderStats(d));
                refreshCpuRank();
                refreshDisk();
            } catch (Exception e) {
                ui.post(() -> { tvStatus.setText("● 连接中断"); tvStatus.setTextColor(C_RED); });
            }
        });
        refreshAlerts();
    }

    private void renderStats(JSONObject d) {
        double cpu = d.optDouble("cpu", 0);
        double mem = d.optDouble("mem_pct", 0);
        double disk = d.optDouble("disk_pct", 0);
        double rx = d.optDouble("rx_mbps", 0);
        double tx = d.optDouble("tx_mbps", 0);
        double memAvail = d.optDouble("mem_available", 0);
        double memTotal = d.optDouble("mem_total", 0);
        double memUsed = d.optDouble("mem_used", 0);
        int uptime = d.optInt("uptime", 0);

        setText(monitorView, R.id.tvCpu, String.format(Locale.US, "%.1f", cpu));
        setText(monitorView, R.id.tvMem, String.format(Locale.US, "%.1f", mem));
        setText(monitorView, R.id.tvDisk, String.format(Locale.US, "%.1f", disk));
        setText(monitorView, R.id.tvRx, String.format(Locale.US, "%.2f", rx));
        setText(monitorView, R.id.tvTx, String.format(Locale.US, "%.2f", tx));
        setText(monitorView, R.id.tvUptime, formatUptime(uptime));
        setText(monitorView, R.id.tvMemDetail, "可用 " + one(memAvail) + " / 共 " + one(memTotal) + " GB");
        setText(monitorView, R.id.tvDiskDetail, "已用 " + one(d.optDouble("disk_used")) + " / 共 " + one(d.optDouble("disk_total")) + " GB");

        ((ProgressBar) monitorView.findViewById(R.id.pbCpu)).setProgress((int) cpu);
        ((ProgressBar) monitorView.findViewById(R.id.pbMem)).setProgress((int) mem);
        ((ProgressBar) monitorView.findViewById(R.id.pbDisk)).setProgress((int) disk);

        double worst = Math.max(cpu, Math.max(mem, disk));
        String health;
        if (worst >= 95) health = "负载很高";
        else if (worst >= 85) health = "负载偏高";
        else health = "运行正常";
        setText(monitorView, R.id.tvHealth, health);
        setText(monitorView, R.id.tvHealthDetail, d.optString("time", ""));
        ((ProgressBar) monitorView.findViewById(R.id.pbHealth)).setProgress((int) worst);

        // 趋势数据
        cpuTrend.add(cpu);
        memTrend.add(mem);
        while (cpuTrend.size() > TREND_MAX) cpuTrend.pollFirst();
        while (memTrend.size() > TREND_MAX) memTrend.pollFirst();
        renderTrend();

        String hostname = d.optString("host", "");
        if (!hostname.isEmpty()) {
            tvHostLabel.setText(hostname + " · 电脑已连接");
        }
        tvUpdated = findViewById(R.id.tvUpdated);
        if (tvUpdated != null) tvUpdated.setText("更新于 " + d.optString("time", ""));
        tvStatus.setText("● 在线");
        tvStatus.setTextColor(C_GREEN);

        renderBattery(d.optJSONObject("battery"));
    }

    // ============ 电池 / 电源状态 ============

    private void renderBattery(JSONObject bat) {
        View root = monitorView;
        boolean present = bat != null && bat.optBoolean("present", false);
        ProgressBar pb = root.findViewById(R.id.pbBat);
        if (bat == null || !present) {
            setText(root, R.id.tvBatPct, "--");
            setText(root, R.id.tvBatStatus, "未检测到电池");
            setText(root, R.id.tvBatDetail, "台式机或读不到电池时显示");
            if (pb != null) pb.setProgress(0);
            return;
        }
        int pct = bat.optInt("percent", 0);
        boolean plugged = bat.optBoolean("plugged", false);
        int mins = bat.optInt("mins_left", -1);
        setText(root, R.id.tvBatPct, String.valueOf(pct));
        setText(root, R.id.tvBatStatus, plugged ? "充电中" : "使用电池");
        String detail;
        if (plugged) {
            detail = "已接通电源，剩余 " + pct + "%";
        } else if (mins > 0) {
            detail = "预计可用约 " + mins + " 分钟";
        } else {
            detail = "剩余 " + pct + "%";
        }
        setText(root, R.id.tvBatDetail, detail);
        if (pb != null) pb.setProgress(Math.max(0, Math.min(100, pct)));
        ((TextView) root.findViewById(R.id.tvBatStatus)).setTextColor(pct <= 20 && !plugged ? C_RED : C_GREEN);
    }

    // ============ 告警 ============

    private void refreshAlerts() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/alerts");
                ui.post(() -> renderAlerts(d.optJSONArray("alerts")));
            } catch (Exception ignored) {
            }
        });
    }

    private void renderAlerts(JSONArray alerts) {
        View banner = monitorView.findViewById(R.id.alertBanner);
        LinearLayout list = monitorView.findViewById(R.id.alertList);
        if (banner == null || list == null) return;
        list.removeAllViews();
        if (alerts == null || alerts.length() == 0) {
            banner.setVisibility(View.GONE);
            return;
        }
        banner.setVisibility(View.VISIBLE);
        for (int i = 0; i < alerts.length(); i++) {
            JSONObject a = alerts.optJSONObject(i);
            if (a == null) continue;
            String level = a.optString("level", "");
            TextView tv = new TextView(MainActivity.this);
            tv.setText("• " + a.optString("message", ""));
            tv.setTextColor(level.equals("critical") ? C_RED : C_ORANGE);
            tv.setTextSize(12);
            tv.setPadding(0, dp(2), 0, dp(2));
            list.addView(tv);
        }
    }

    private String one(double v) {
        return String.format(Locale.US, "%.1f", v);
    }

    private String formatUptime(int s) {
        int d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
        return d > 0 ? (d + "天 " + h + "小时") : (h + "小时 " + m + "分钟");
    }

    // ============ 趋势图 ============

    private void renderTrend() {
        TextView label = monitorView.findViewById(R.id.tvTrendLabel);
        if (label != null) label.setText(showMemTrend ? "内存" : "CPU");
        LinearLayout canvas = monitorView.findViewById(R.id.trendCanvas);
        if (canvas == null) return;
        canvas.removeAllViews();
        java.util.Deque<Double> data = showMemTrend ? memTrend : cpuTrend;
        if (data.isEmpty()) return;
        int n = data.size();
        int barH = 56;
        int maxW = (int) (dp(300) / Math.max(n, 1));
        for (Double v : data) {
            int h = (int) Math.round(barH * Math.min(100.0, Math.max(1.0, v)) / 100.0);
            LinearLayout col = new LinearLayout(MainActivity.this);
            col.setOrientation(LinearLayout.VERTICAL);
            col.setGravity(android.view.Gravity.BOTTOM);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(Math.max(dp(2), maxW - dp(2)), dp(barH));
            lp.setMargins(dp(1), 0, dp(1), 0);
            col.setLayoutParams(lp);
            View bar = new View(MainActivity.this);
            bar.setBackgroundColor(showMemTrend ? C_GREEN : C_BLUE);
            LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, h == 0 ? dp(2) : dp(h));
            bar.setLayoutParams(blp);
            col.addView(bar);
            canvas.addView(col);
        }
    }

    // ============ CPU 占用排行 ============

    private void refreshCpuRank() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/processes/cpu");
                ui.post(() -> {
                    cpuBaseReady = true;
                    setText(monitorView, R.id.tvCpuRankHint, "按 CPU 使用率排序（每数秒更新）");
                    renderCpuRank(d.optJSONArray("processes"));
                });
            } catch (Exception ignored) {
            }
        });
    }

    private void renderCpuRank(JSONArray arr) {
        LinearLayout list = monitorView.findViewById(R.id.cpuRankList);
        if (list == null) return;
        list.removeAllViews();
        if (arr == null || arr.length() == 0) {
            TextView t = new TextView(MainActivity.this);
            t.setText(cpuBaseReady ? "暂无数据" : "等待首次采样完成…");
            t.setTextColor(C_MUTED);
            list.addView(t);
            return;
        }
        for (int i = 0; i < arr.length(); i++) {
            JSONObject p = arr.optJSONObject(i);
            double pct = p.optDouble("cpu_pct", 0);
            if (pct < 0.5) continue;
            LinearLayout row = new LinearLayout(MainActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(android.view.Gravity.CENTER_VERTICAL);
            TextView name = new TextView(MainActivity.this);
            String pname = p.optString("name", "?");
            if (pname.length() > 26) pname = pname.substring(0, 24) + "…";
            name.setText(pname);
            name.setTextColor(C_MUTED);
            name.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            TextView pctv = new TextView(MainActivity.this);
            pctv.setText(String.format(Locale.US, "%.0f%%", pct));
            pctv.setTextColor(pct >= 50 ? C_RED : C_GREEN);
            pctv.setPadding(dp(10), dp(6), 0, dp(6));
            row.addView(name);
            row.addView(pctv);
            list.addView(row);
        }
    }

    // ============ 磁盘分区 ============

    private void refreshDisk() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/disk");
                ui.post(() -> renderDisk(d.optJSONArray("partitions")));
            } catch (Exception ignored) {
            }
        });
    }

    private void renderDisk(JSONArray arr) {
        LinearLayout list = monitorView.findViewById(R.id.diskList);
        if (list == null) return;
        list.removeAllViews();
        if (arr == null || arr.length() == 0) {
            TextView t = new TextView(MainActivity.this);
            t.setText("没有可显示的分区");
            t.setTextColor(C_MUTED);
            list.addView(t);
            return;
        }
        for (int i = 0; i < arr.length(); i++) {
            JSONObject p = arr.optJSONObject(i);
            double pct = Math.max(0, Math.min(100, p.optDouble("percent", 0)));
            double used = p.optDouble("used_gb", 0);
            double total = p.optDouble("total_gb", 0);
            // 过滤光驱等无效分区（后端也过滤，这里再加一道保险）
            if (total < 1.0 && pct >= 99) continue;
            LinearLayout item = new LinearLayout(MainActivity.this);
            item.setOrientation(LinearLayout.VERTICAL);
            LinearLayout head = new LinearLayout(MainActivity.this);
            head.setOrientation(LinearLayout.HORIZONTAL);
            head.setGravity(android.view.Gravity.CENTER_VERTICAL);
            TextView mp = new TextView(MainActivity.this);
            String mpStr = p.optString("mountpoint", "?");
            if (mpStr.length() > 4) mpStr = mpStr.replace("\\", "") + ":";
            mp.setText(mpStr.toUpperCase(Locale.US));
            mp.setTextColor(C_BLUE);
            mp.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            TextView usage = new TextView(MainActivity.this);
            usage.setText(String.format(Locale.US, "%.0f / %.0f GB · %.0f%%", used, total, pct));
            usage.setTextColor(C_MUTED);
            head.addView(mp);
            head.addView(usage);
            item.addView(head);
            // 进度条：彩色填充 + 底色
            LinearLayout barWrap = new LinearLayout(MainActivity.this);
            barWrap.setOrientation(LinearLayout.HORIZONTAL);
            View bar = new View(MainActivity.this);
            bar.setBackgroundColor(pct >= 90 ? C_RED : (pct >= 75 ? C_ORANGE : C_GREEN));
            LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(0, dp(6));
            blp.weight = (float) (pct / 100.0);
            barWrap.addView(bar, blp);
            View emptyBg = new View(MainActivity.this);
            emptyBg.setBackgroundColor(0x223453);
            LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(0, dp(6));
            elp.weight = (float) (1.0 - pct / 100.0);
            barWrap.addView(emptyBg, elp);
            item.addView(barWrap);
            item.setPadding(0, dp(5), 0, dp(2));
            list.addView(item);
        }
    }

    // ============ 电脑快捷操作 ============

    private void quickAction(final String action) {
        toast("正在执行…");
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/action", "{\"action\":\"" + action + "\"}", true);
                ui.post(() -> toast(d.optBoolean("ok", false) ? d.optString("message", "已打开") : "失败：" + d.optString("message", "")));
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    // ============ 电源控制（二次确认） ============

    private void confirmPower(final String action, final String label) {
        final String msg = "确定要" + label + "这台电脑吗？\n该操作会" + (action.equals("system_sleep") ? "让电脑进入睡眠，网络可能中断。" : "中断与电脑的连接。");
        new AlertDialog.Builder(MainActivity.this)
                .setTitle("确认" + label)
                .setMessage(msg)
                .setPositiveButton("确定" + label, (d, w) -> doPower(action, label))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doPower(final String action, final String label) {
        toast("正在发送" + label + "指令…");
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/action", "{\"action\":\"" + action + "\",\"confirm\":true}", true);
                ui.post(() -> toast(d.optBoolean("ok", false) ? d.optString("message", "指令已发送") : "失败：" + d.optString("message", "")));
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    // ============ 结束进程（二次确认） ============

    private void confirmKill(final int pid, final String pname) {
        new AlertDialog.Builder(MainActivity.this)
                .setTitle("确认结束进程")
                .setMessage("确定要结束进程「" + pname + "」(PID " + pid + ") 吗？\n未保存的数据可能会丢失。")
                .setPositiveButton("结束进程", (d, w) -> doKill(pid, pname))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doKill(final int pid, final String pname) {
        toast("正在结束进程…");
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/processes/kill",
                        "{\"pid\":" + pid + ",\"name\":" + org.json.JSONObject.quote(pname) + ",\"confirm\":true}",
                        true);
                ui.post(() -> {
                    boolean ok = d.optBoolean("ok", false);
                    toast(ok ? d.optString("message", "已结束") : ("失败：" + d.optString("message", "")));
                    if (ok) loadProcesses(); // 刷新进程列表
                });
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    private void doOptimize() {
        final Button b = toolsView.findViewById(R.id.btnOptimize);
        b.setEnabled(false);
        setText(toolsView, R.id.tvOptimizeResult, "正在筛选普通应用并整理工作集…");
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/action", "{\"action\":\"memory_optimize\"}", true);
                ui.post(() -> {
                    if (d.optBoolean("ok", false)) {
                        String warn = d.optString("warning", "");
                        setText(toolsView, R.id.tvOptimizeResult,
                                "整理成功：" + d.optInt("trimmed_processes", 0) + " 个；跳过：" + d.optInt("skipped_processes", 0) + " 个。\n可用内存 " + d.optString("available_before_gb", "?") + " → " + d.optString("available_after_gb", "?") + " GB。\n" + warn);
                    } else {
                        setText(toolsView, R.id.tvOptimizeResult, "操作失败：" + d.optString("message", ""));
                    }
                });
            } catch (Exception e) {
                ui.post(() -> setText(toolsView, R.id.tvOptimizeResult, "无法连接电脑服务"));
            } finally {
                ui.post(() -> b.setEnabled(true));
            }
        });
    }

    private void loadProcesses() {
        final Button b = toolsView.findViewById(R.id.btnProcesses);
        b.setEnabled(false);
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/processes");
                final JSONArray arr = d.optJSONArray("processes");
                ui.post(() -> {
                    LinearLayout list = toolsView.findViewById(R.id.processList);
                    list.removeAllViews();
                    if (arr == null) {
                        TextView t = new TextView(MainActivity.this);
                        t.setText("没有可显示的进程");
                        t.setTextColor(C_MUTED);
                        list.addView(t);
                    } else {
                        for (int i = 0; i < arr.length(); i++) {
                            final JSONObject p = arr.optJSONObject(i);
                            final String pname = p.optString("name", "");
                            final int pid = p.optInt("pid", 0);
                            LinearLayout row = new LinearLayout(MainActivity.this);
                            row.setOrientation(LinearLayout.HORIZONTAL);
                            row.setGravity(android.view.Gravity.CENTER_VERTICAL);
                            TextView name = new TextView(MainActivity.this);
                            name.setText(pname.length() > 22 ? pname.substring(0, 21) + "…" : pname);
                            name.setTextColor(C_MUTED);
                            name.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
                            TextView mb = new TextView(MainActivity.this);
                            mb.setText(String.format(Locale.US, "%.0f MB", p.optDouble("memory_mb", 0)));
                            mb.setTextColor(C_MUTED);
                            mb.setPadding(dp(8), dp(6), 0, dp(6));
                            row.addView(name);
                            row.addView(mb);
                            Button killBtn = new Button(MainActivity.this);
                            killBtn.setText("结束");
                            killBtn.setTextColor(C_RED);
                            killBtn.setTextSize(11);
                            killBtn.setBackgroundColor(0x22FF667F);
                            killBtn.setPadding(dp(6), dp(3), dp(6), dp(3));
                            killBtn.setAllCaps(false);
                            killBtn.setStateListAnimator(null);
                            killBtn.setOnClickListener(v -> confirmKill(pid, pname));
                            row.addView(killBtn);
                            list.addView(row);
                        }
                    }
                });
            } catch (Exception e) {
                ui.post(() -> { /* ignore */ });
            } finally {
                ui.post(() -> b.setEnabled(true));
            }
        });
    }

    private void refreshTools() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/stats");
                ui.post(() -> {
                    setText(toolsView, R.id.tvMemPagePct, one(d.optDouble("mem_pct")) + "%");
                    setText(toolsView, R.id.tvMemPageAvail, one(d.optDouble("mem_available")) + " GB");
                });
            } catch (Exception ignored) {
            }
        });
        loadVolume();
    }

    // ============ 媒体 & 音量 ============

    private void loadVolume() {
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/volume");
                JSONObject vol = d.optJSONObject("volume");
                ui.post(() -> {
                    if (vol == null) return;
                    int pct = vol.optInt("volume_pct", 0);
                    setText(toolsView, R.id.tvVolPct, pct + "%");
                    SeekBar sb = toolsView.findViewById(R.id.volSeek);
                    if (sb != null) sb.setProgress(pct);
                    boolean muted = vol.optBoolean("muted", false);
                    setText(toolsView, R.id.tvVolStatus,
                            muted ? "已静音" : (vol.optBoolean("ok", false) ? "当前音量" : "未返回"));
                });
            } catch (Exception ignored) {
            }
        });
    }

    private void doSetVolume(final int level) {
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/action", "{\"action\":\"volume_set\",\"level\":"
                        + level + "}", true);
                ui.post(() -> {
                    setText(toolsView, R.id.tvVolStatus, d.optString("message", ""));
                    JSONObject vol = d.optJSONObject("volume");
                    if (vol != null) {
                        setText(toolsView, R.id.tvVolPct, vol.optInt("volume_pct", level) + "%");
                        SeekBar sb = toolsView.findViewById(R.id.volSeek);
                        if (sb != null) sb.setProgress(vol.optInt("volume_pct", level));
                    }
                });
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    private void doVolumeDelta(final int delta) {
        io.execute(() -> {
            try {
                JSONObject d = apiPost("/api/action", "{\"action\":\"volume_set\",\"delta\":"
                        + delta + "}", true);
                ui.post(() -> {
                    setText(toolsView, R.id.tvVolStatus, d.optString("message", ""));
                    JSONObject vol = d.optJSONObject("volume");
                    if (vol != null) {
                        setText(toolsView, R.id.tvVolPct, vol.optInt("volume_pct", 0) + "%");
                        SeekBar sb = toolsView.findViewById(R.id.volSeek);
                        if (sb != null) sb.setProgress(vol.optInt("volume_pct", 0));
                    }
                });
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    // ============ 剪贴板互通 ============

    private void readClipboard() {
        toast("正在读取电脑剪贴板…");
        io.execute(() -> {
            try {
                JSONObject d = apiGet("/api/clipboard");
                ui.post(() -> {
                    if (d.optBoolean("ok", false)) {
                        EditText et = toolsView.findViewById(R.id.clipText);
                        if (et != null) et.setText(d.optString("text", ""));
                        toast("已读取电脑剪贴板");
                    } else {
                        toast("读取失败：" + d.optString("message", ""));
                    }
                });
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    private void writeClipboard() {
        EditText et = toolsView.findViewById(R.id.clipText);
        if (et == null) return;
        String text = et.getText().toString();
        if (text.isEmpty()) {
            toast("请先输入要写入的文字");
            return;
        }
        hideKeyboard();
        toast("正在写入电脑剪贴板…");
        io.execute(() -> {
            try {
                String payload = "{\"text\":" + org.json.JSONObject.quote(text) + "}";
                JSONObject d = apiPost("/api/clipboard", payload, true);
                ui.post(() -> toast(d.optBoolean("ok", false) ? "已写入电脑剪贴板" : "写入失败：" + d.optString("message", "")));
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    // ============ 电脑推送通知 ============

    private void sendNotify() {
        EditText t = toolsView.findViewById(R.id.notifyTitle);
        EditText m = toolsView.findViewById(R.id.notifyMsg);
        String title = t == null ? "" : t.getText().toString().trim();
        String msg = m == null ? "" : m.getText().toString();
        if (title.isEmpty() && msg.isEmpty()) {
            toast("请先填写通知标题或内容");
            return;
        }
        hideKeyboard();
        toast("正在推送…");
        final String ft = title, fm = msg;
        io.execute(() -> {
            try {
                String payload = "{\"title\":" + org.json.JSONObject.quote(ft)
                        + ",\"message\":" + org.json.JSONObject.quote(fm) + "}";
                JSONObject d = apiPost("/api/notify", payload, true);
                ui.post(() -> toast(d.optBoolean("ok", false) ? d.optString("message", "已推送") : "推送失败：" + d.optString("message", "")));
            } catch (Exception e) {
                ui.post(() -> toast("无法连接电脑服务"));
            }
        });
    }

    // ============ HTTP ============

    private static final int PORT = 8000;
    private static final int REQ_SCAN = 200;

    private String hostPort() {
        if (host.contains(":")) {
            return host;
        }
        return host + ":" + PORT;
    }

    private JSONObject apiGet(String path) throws Exception {
        return apiGet(path, 4000);
    }

    // 截图等耗时操作使用更长读超时（adb 抓屏 + 热点慢速传输）
    private JSONObject apiGet(String path, int readTimeoutMs) throws Exception {
        String url = "http://" + hostPort() + path;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(4000);
        conn.setReadTimeout(readTimeoutMs);
        conn.setRequestProperty("Authorization", "Bearer " + token);
        conn.setRequestProperty("Cache-Control", "no-store");
        int code = conn.getResponseCode();
        if (code == 401) {
            ui.post(() -> { token = ""; prefs.edit().remove(KEY_TOKEN).apply(); showPage("pair"); });
            throw new Exception("auth_required");
        }
        String body = read(conn.getInputStream());
        conn.disconnect();
        return new JSONObject(body);
    }

    private JSONObject apiPost(String path, String payload, boolean auth) throws Exception {
        String url = "http://" + hostPort() + path;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(4000);
        conn.setReadTimeout(6000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Cache-Control", "no-store");
        if (auth) {
            conn.setRequestProperty("Authorization", "Bearer " + token);
        }
        OutputStream os = conn.getOutputStream();
        os.write(payload.getBytes(StandardCharsets.UTF_8));
        os.flush();
        os.close();
        int code = conn.getResponseCode();
        if (code == 401) {
            ui.post(() -> { token = ""; prefs.edit().remove(KEY_TOKEN).apply(); showPage("pair"); });
            throw new Exception("auth_required");
        }
        String body = read(conn.getInputStream());
        conn.disconnect();
        return new JSONObject(body);
    }

    private String read(java.io.InputStream in) throws Exception {
        BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) sb.append(line);
        r.close();
        return sb.toString();
    }

    private void setText(View root, int id, String value) {
        View v = root.findViewById(id);
        if (v instanceof TextView) ((TextView) v).setText(value);
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        View v = getCurrentFocus();
        if (imm != null && v != null) imm.hideSoftInputFromWindow(v.getWindowToken(), 0);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }
}
