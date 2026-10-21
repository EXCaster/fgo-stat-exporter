package io.github.ayamedog.fgostats;

import android.app.Instrumentation;
import android.os.Bundle;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/** 在目标安卓解释器中运行人工数据检查，只返回错误类型和代码位置。 */
public final class BackendProbe extends Instrumentation {
    private int inputPort;
    private boolean gachaMode;
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments != null) {
            gachaMode = "gachas".equals(arguments.getString("mode", ""));
            try { inputPort = Integer.parseInt(arguments.getString("input_port", "0")); }
            catch (NumberFormatException ignored) { }
        }
        if (inputPort < 1024 || inputPort > 65535) inputPort = 0;
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            ResourceInstaller.prepare(getTargetContext());
            if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
            String script =
                "import json,traceback,threading,time,urllib.request\n" +
                "from pathlib import Path\n" +
                "result={}\n" +
                "try:\n" +
                " from fgo_local_exporter.mobile import MobileRuntime\n" +
                " root=Path(ROOT)\n" +
                " app=MobileRuntime(str(root),str(root/'public-resources'))\n" +
                " raw=json.dumps({'response':[{'nid':'login','resCode':'00','success':{}}]," +
                "'cache':{'serverTime':1792500000,'replaced':{'userGame':[{" +
                "'userId':123,'friendCode':'123456789012','name':'人工测试','rkchannel':24," +
                "'createdAt':1477000000,'lv':1}],'userSvt':[],'userSvtCollection':[]}}}).encode()\n" +
                " if INPUT_PORT:\n" +
                "  with urllib.request.urlopen('http://127.0.0.1:'+str(INPUT_PORT)+'/',timeout=10) as source:raw=source.read(16*1024*1024+1)\n" +
                " started=time.monotonic()\n" +
                " if GACHA_MODE:\n" +
                "  from fgo_stat_core.features.report.gacha_records import gacha_page\n" +
                "  history=app._store.builder.gacha_history(raw)\n" +
                "  page=gacha_page(history)\n" +
                "  assert history.available and page['total']==len(history.records)\n" +
                "  assert len(page['rows'])<=30\n" +
                "  result={'ok':True,'seconds':round(time.monotonic()-started,2),'records':len(history.records),'pages':page['pages'],'page_rows':len(page['rows'])}\n" +
                " else:\n" +
                "  document=app._store.builder.render(raw,{'friend':False,'support':True},threading.Event())\n" +
                "  result={'ok':True,'seconds':round(time.monotonic()-started,2),'html_bytes':len(document.html),'assets':len(document.assets)}\n" +
                " raw=None\n" +
                " app.close()\n" +
                "except BaseException as error:\n" +
                " while error.__context__ is not None:error=error.__context__\n" +
                " result={'ok':False,'type':type(error).__name__,'frames':[(Path(f.filename).name,f.name,f.lineno) for f in traceback.extract_tb(error.__traceback__)]}\n" +
                " if isinstance(error,ModuleNotFoundError):result['module']=error.name\n" +
                " if isinstance(error,FileNotFoundError):result['file']=Path(error.filename).name\n" +
                " if isinstance(error,ImportError):\n" +
                "  import re\n" +
                "  message=str(error)\n" +
                "  match=re.search(r'cannot import name [\\\"\\\']([A-Za-z0-9_]+)',message)\n" +
                "  if match:result['symbol']=match.group(1)\n" +
                "  match=re.search(r'cannot locate symbol [\\\"\\\']([A-Za-z0-9_]+)',message)\n" +
                "  if match:result['native_symbol']=match.group(1)\n" +
                "  result['library_load_failure']='dlopen failed' in message\n" +
                "RESULT=json.dumps(result,ensure_ascii=False)\n";
            com.chaquo.python.PyObject namespace = Python.getInstance().getBuiltins().callAttr("dict");
            namespace.callAttr("__setitem__", "ROOT", getTargetContext().getFilesDir().getPath());
            namespace.callAttr("__setitem__", "INPUT_PORT", inputPort);
            namespace.callAttr("__setitem__", "GACHA_MODE", gachaMode);
            Python.getInstance().getBuiltins().callAttr("exec", script, namespace);
            result.putString("probe", namespace.callAttr("__getitem__", "RESULT").toString());
        } catch (Exception error) { result.putString("probe", "PROBE_FAILED:" + error.getClass().getSimpleName()); }
        finish(-1, result);
    }
}
