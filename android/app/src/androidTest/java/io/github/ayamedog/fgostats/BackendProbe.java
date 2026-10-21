package io.github.ayamedog.fgostats;

import android.app.Instrumentation;
import android.os.Bundle;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/** 在目标安卓解释器中运行人工数据检查，只返回错误类型和代码位置。 */
public final class BackendProbe extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
            String script =
                "import json,traceback,threading\n" +
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
                " document=app._store.builder.render(raw,{'friend':False,'support':True},threading.Event())\n" +
                " result={'ok':True,'html_bytes':len(document.html),'assets':len(document.assets)}\n" +
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
            Python.getInstance().getBuiltins().callAttr("exec", script, namespace);
            result.putString("probe", namespace.callAttr("__getitem__", "RESULT").toString());
        } catch (Exception error) { result.putString("probe", "PROBE_FAILED:" + error.getClass().getSimpleName()); }
        finish(-1, result);
    }
}
