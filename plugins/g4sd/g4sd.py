from PySide6 import QtCore, QtGui, QtWidgets

class ui_g4xp(object):
    def setupUi(self, window):
        window.setObjectName("G4SD")
        self.horizontalLayout = QtWidgets.QHBoxLayout(window)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.tabWidget = QtWidgets.QTabWidget(window)
        self.tabWidget.setObjectName("tabWidget")
        self.tab = QtWidgets.QWidget()
        self.tab.setObjectName("tab")
        self.horizontalLayout_4 = QtWidgets.QHBoxLayout(self.tab)
        self.horizontalLayout_4.setObjectName("horizontalLayout_4")
        self.about = QtWidgets.QTextBrowser(self.tab)
        self.about.setObjectName("g4sd")
        self.horizontalLayout_4.addWidget(self.about)
        self.tabWidget.addTab(self.tab, "")
        self.tab_2 = QtWidgets.QWidget()
        self.tab_2.setObjectName("tab_2")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout(self.tab_2)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.license = QtWidgets.QTextBrowser(self.tab_2)
        self.license.setOpenExternalLinks(True)
        self.license.setObjectName("g4sd_license")
        self.horizontalLayout_2.addWidget(self.jg_license)
        self.tabWidget.addTab(self.tab_2, "")
        self.tab_3 = QtWidgets.QWidget()
        self.tab_3.setObjectName("tab_3")
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout(self.tab_3)
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        self.third_party_licenses = QtWidgets.QTextBrowser(self.tab_3)
        self.third_party_licenses.setOpenExternalLinks(True)
        self.third_party_licenses.setObjectName("third_party_licenses")
        self.horizontalLayout_3.addWidget(self.third_party_licenses)
        self.tabWidget.addTab(self.tab_3, "")
        self.horizontalLayout.addWidget(self.tabWidget)

        self.retranslateUi(window)
        self.tabWidget.setCurrentIndex(0)
        QtCore.QMetaObject.connectSlotsByName(window)

    def retranslateUi(self, window):
        _translate = QtCore.QCoreApplication.translate
        window.setWindowTitle(_translate("About", "About G4SD"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), _translate("About", "About"))
        self.license.setHtml(_translate("About", "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n"
"<html><head><meta name=\"qrichtext\" content=\"1\" /><style type=\"text/css\">\n"
"p, li { white-space: pre-wrap; }\n"
"</style></head><body style=\" font-family:\'MS Shell Dlg 2\'; font-size:8.25pt; font-weight:400; font-style:normal;\">\n"
"<p style=\"-qt-paragraph-type:empty; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px; font-size:8pt;\"><br /></p></body></html>"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_2), _translate("About", "License"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_3), _translate("About", "3rd Party Licenses"))



class g4sd_dialog(common.BaseDialogUi):

    """Widget which displays information about the application."""

    def __init__(self, parent=None):
        """Creates a new about widget.

        This creates a simple widget which shows version information
        and various software licenses.

        :param parent parent of this widget
        """
        super().__init__(parent)
        self.ui = ui_g4xp()
        self.ui.setupUi(self)

        # # self.ui.about.setHtml(
        # #     open(gremlin.util.resource_path("about/about.html")).read()
        # # )

        # # self.ui.jg_license.setHtml(
        # #     open(gremlin.util.resource_path("about/joystick_gremlin.html")).read()
        # # )

        # license_list = [
        #     "about/third_party_licenses.html",
        #     "about/modernuiicons.html",
        #     "about/pyqt.html",
        #     "about/pywin32.html",
        #     "about/qt5.html",
        #     "about/reportlab.html",
        #     "about/vjoy.html",
        # ]
        # third_party_licenses = ""
        # for fname in license_list:
        #     third_party_licenses += open(gremlin.util.resource_path(fname)).read()
        #     third_party_licenses += "<hr>"
        # self.ui.third_party_licenses.setHtml(third_party_licenses)

