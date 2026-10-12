import json
import re
from importlib.resources import files

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QAbstractButton, QComboBox, QStyle, QStyleOptionComboBox
from legiongobar.backend import Backend
from legiongobar.storage import Store
from legiongobar.i18n import I18n
from legiongobar.ui.window import Window
from legiongobar.ui.chrome import TitleBar
from legiongobar.ui.theme import FONT_FAMILY

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def window(app,tmp_path):
    store=Store(tmp_path)
    result=Window(Backend(store,demo=True),store,no_tray=True,i18n=I18n("zh_CN"))
    result.show()
    result.pool.waitForDone()
    app.processEvents()
    yield result
    result.quit()
    result.pool.waitForDone()
    app.removeEventFilter(result)
    result.deleteLater()
    app.processEvents()

def test_all_rendered_chinese_captions_are_translated_or_deliberate_terms(app,window):
    terms=set(json.loads(files("legiongobar").joinpath("locales/technical_terms.json").read_text(encoding="utf-8")))
    missing=set()
    for tab in window.tab_ids:
        window.select(tab)
        app.processEvents()
        for obj in window.findChildren(QWidget):
            sources=[]
            for method in ("setText","setToolTip","setPlaceholderText"):
                prop=obj.property("translation_"+method)
                if prop:
                    sources.append(prop["source"])
            if isinstance(obj,QComboBox):
                sources.extend(obj.property("translation_items") or [])
            for source in sources:
                if re.search(r"[A-Za-z]{2}",source) and not source.startswith("{"):
                    if source == window.i18n.text(source) and source not in terms:
                        missing.add(source)
    assert not missing, sorted(missing)

def test_technical_feature_names_stay_in_english(window):
    for source in ("AFMF","RSR","Radeon Super Resolution","Fluid Motion Frames","Radeon Anti-Lag","Radeon Boost","Radeon Chill","CPU Boost","AutoTDP","Lossless Scaling"):
        assert window.i18n.text(source)==source

@pytest.mark.parametrize("language", ["zh_CN","en_US"])
@pytest.mark.parametrize("size", [(560,480),(600,670),(800,850)])
def test_title_bar_and_display_values_fit(app,window,language,size):
    window.i18n.set_language(language)
    window.resize(*size)
    window.select("AMD")
    app.processEvents()
    assert QApplication.font().family()==FONT_FAMILY
    bar=window.findChild(TitleBar)
    for button in bar.findChildren(QAbstractButton):
        assert bar.rect().contains(button.geometry())
        assert button.width()>=36 and button.height()>=32
        assert not button.icon().isNull()
        assert button.font().family()==FONT_FAMILY
    for name in ("ResolutionComboBox","RefreshRatesComboBox"):
        combo=window.renderer.named[name]
        option=QStyleOptionComboBox()
        combo.initStyleOption(option)
        text_rect=combo.style().subControlRect(QStyle.CC_ComboBox,option,QStyle.SC_ComboBoxEditField,combo)
        arrow_rect=combo.style().subControlRect(QStyle.CC_ComboBox,option,QStyle.SC_ComboBoxArrow,combo)
        assert text_rect.width()>=combo.fontMetrics().horizontalAdvance(combo.currentText())
        assert combo.rect().contains(arrow_rect) and arrow_rect.width()>=14
        assert combo.font().family()==FONT_FAMILY
        assert not combo.isEditable()
    # 展开按钮用 SVG 图标，不依赖正文中文字体中的特殊字符。
    expand=window.renderer.named["ColorSettingsExpandButton"]
    assert not expand.icon().isNull() and expand.text()==""

def test_language_switch_retranslates_existing_status_message(window):
    window.i18n.bind(window.status,"{key}: {value} · {message}",key="CPUBoost",value=True,message="Read back from hardware")
    assert "设备已回读确认" in window.status.text()
    window.i18n.set_language("en_US")
    assert "Read back from hardware" in window.status.text()
