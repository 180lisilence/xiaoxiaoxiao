package com.xiaoxiaoxiao.workbench;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
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
        webView.addJavascriptInterface(new LocalBridge(db), "AndroidLocal");

        webView.setWebViewClient(new AppWebViewClient());
        webView.setWebChromeClient(new AppChromeClient(this));

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            webView.loadUrl(ENTRY);
        }
    }

    /** 只允许 assets 内部导航，外链一律不跳出应用。 */
    static final class AppWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return url == null || !url.startsWith("file:///android_asset/");
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
