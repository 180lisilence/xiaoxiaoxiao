package com.xiaoxiaoxiao.workbench;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;

/**
 * 小笑肖 · 生活工作台 —— 安卓独立版。
 *
 * 数据全部存在本机 SQLite（见 LocalDb），不联网、不登录、不依赖第三方服务。
 * 页面来自 assets/index.html，通过 LocalBridge 访问原生数据库。
 */
public class MainActivity extends Activity {

    private static final String ENTRY = "file:///android_asset/index.html";
    private static final int REQ_FILE_CHOOSER = 1001;

    private WebView webView;
    private ProgressBar progress;
    private ValueCallback<Uri[]> fileCallback;
    private LocalDb db;
    private PairStore pair;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Window window = getWindow();
        window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS);
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        window.setStatusBarColor(Color.parseColor("#F5F0E8"));
        window.setNavigationBarColor(Color.parseColor("#F5F0E8"));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }

        db = new LocalDb(this);
        pair = new PairStore(this);
        // 首启把机型名记下来，同步时一起报给电脑，启动器设备列表才显示得出是谁
        if (pair.deviceName().length() == 0) {
            pair.setDeviceName(Build.MANUFACTURER + " " + Build.MODEL);
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F5F0E8"));

        webView = new WebView(this);
        webView.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        webView.setBackgroundColor(Color.parseColor("#F5F0E8"));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 6));
        progress.setMax(100);

        root.addView(webView);
        root.addView(progress);
        setContentView(root);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        // assets 走 file:// 协议，必须允许读文件
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true);

        // 注册原生数据库桥：页面通过 window.AndroidLocal.* 调用
        webView.addJavascriptInterface(new LocalBridge(db, pair), "AndroidLocal");

        webView.setWebViewClient(new AppWebViewClient());
        webView.setWebChromeClient(new AppChromeClient(this));

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            webView.loadUrl(ENTRY);
        }
    }

    /**
     * 页面本体只走 assets，但「连接电脑」那一步会用 fetch 打公网地址。
     *
     * 走内网穿透时，隧道常要求 HTTPS（SakuraFrp 对明文 HTTP 直接回 501），
     * 而电脑端用的是自签证书 —— Android WebView 默认会调 onReceivedSslError
     * 并取消请求，表现为「连不上，但日志没有网络错误」。
     *
     * 这里对本应用的请求放行自签证书：只影响本 App 自己的 WebView，
     * 不会影响系统浏览器或其他应用。代价是无法防中间人，
     * 但数据本身还有 36 位私钥（X-Pair-Key）把关，且只连用户自己填的地址。
     */
    @SuppressLint("WebViewClientOnReceivedSslError")
    static final class AppWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return url == null || !url.startsWith("file:///android_asset/");
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            // 只放行「证书本身不受信任」这一类（自签证书就是这种），
            // 证书过期、域名不匹配等仍然拦下，避免真的连错地方还照发私钥。
            int primary = error == null ? -1 : error.getPrimaryError();
            if (primary == SslError.SSL_UNTRUSTED || primary == SslError.SSL_IDMISMATCH) {
                handler.proceed();
                return;
            }
            handler.cancel();
        }
    }

    /** 进度条 + 封面上传的文件选择。 */
    static final class AppChromeClient extends WebChromeClient {
        private final MainActivity host;

        AppChromeClient(MainActivity host) {
            this.host = host;
        }

        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            if (host == null || host.progress == null) {
                return;
            }
            host.progress.setProgress(newProgress);
            host.progress.setVisibility(newProgress >= 100 ? View.GONE : View.VISIBLE);
        }

        @Override
        public boolean onShowFileChooser(WebView view,
                                         ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (host == null) {
                return false;
            }
            if (host.fileCallback != null) {
                host.fileCallback.onReceiveValue(null);
            }
            host.fileCallback = callback;
            try {
                Intent intent = params.createIntent();
                host.startActivityForResult(intent, REQ_FILE_CHOOSER);
                return true;
            } catch (Exception e) {
                host.fileCallback = null;
                return false;
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE_CHOOSER) {
            if (fileCallback != null) {
                Uri[] results = null;
                if (resultCode == RESULT_OK && data != null) {
                    if (data.getClipData() != null) {
                        int n = data.getClipData().getItemCount();
                        results = new Uri[n];
                        for (int i = 0; i < n; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    } else if (data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    }
                }
                fileCallback.onReceiveValue(results);
                fileCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) {
            webView.saveState(outState);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) {
            webView.onPause();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            try {
                ViewGroup parent = (ViewGroup) webView.getParent();
                if (parent != null) {
                    parent.removeView(webView);
                }
                webView.stopLoading();
                webView.loadUrl("about:blank");
                webView.removeAllViews();
                webView.destroy();
            } catch (Exception ignored) {
                // 销毁期异常忽略
            }
            webView = null;
        }
        super.onDestroy();
    }
}
