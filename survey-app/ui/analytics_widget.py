"""Analytics dashboard widget — KPI cards + three PyQtChart charts."""
import logging
from datetime import date

from PyQt6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries, QBarSet,
    QChart, QChartView,
    QPieSeries,
    QValueAxis,
)
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QDateEdit, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from services.analytics import get_analytics_summary, AnalyticsSummary

log = logging.getLogger(__name__)

# colour palette
_GREEN  = "#28a745"
_YELLOW = "#ffc107"
_RED    = "#dc3545"
_BLUE   = "#0d6efd"
_GRAY   = "#6c757d"

# Pie slice colours for situation statuses
_PIE_COLORS = [
    QColor("#FFC107"),  # in_progress – amber
    QColor("#28A745"),  # resolved    – green
    QColor("#DC3545"),  # unresolved  – red
    QColor("#6C757D"),  # closed      – gray
]

# Pie slice colours for contact type distribution (fallback)
_PIE_CONTACT_COLORS = [
    QColor("#0D6EFD"),  # Плановый 1   – blue
    QColor("#6F42C1"),  # Плановый 2   – purple
    QColor("#20C997"),  # Плановый 3   – teal
    QColor("#FD7E14"),  # Дополнительный – orange
    QColor("#6C757D"),  # Не указан    – gray
]


# ---------------------------------------------------------------------------
# KPI card helper
# ---------------------------------------------------------------------------

class _KpiCard(QFrame):
    """Compact coloured card: title on top, big value in the middle."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet("font-size: 12px; color: #444;")

        self._value_lbl = QLabel("—")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setStyleSheet("font-size: 26px; font-weight: bold;")

        layout.addWidget(self._title_lbl)
        layout.addWidget(self._value_lbl)

    def set_value(self, text: str, color: str = "#212529") -> None:
        self._value_lbl.setText(text)
        self._value_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {color};"
        )


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class AnalyticsWidget(QWidget):
    """Analytics tab: period selector, KPI cards, and three charts."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._summary: AnalyticsSummary | None = None
        self._dark = False
        self._pie_colors: list[QColor] = list(_PIE_COLORS)
        self._build_ui()
        self.load_data()

    def set_dark_theme(self, dark: bool) -> None:
        """Switch chart theme without reloading data from DB."""
        self._dark = dark
        chart_theme = (
            QChart.ChartTheme.ChartThemeDark
            if dark else
            QChart.ChartTheme.ChartThemeLight
        )
        bg = QBrush(QColor("#1a1d21" if dark else "#ffffff"))
        for view in (self._trend_view, self._pie_view):
            chart = view.chart()
            if chart:
                chart.setTheme(chart_theme)
                chart.setBackgroundBrush(bg)
        # Re-apply custom series colours that theme may have overridden
        self._reapply_series_colors()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Top bar: period selector + refresh ────────────────────────
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Период:"))

        self._all_btn = QPushButton("Весь период")
        self._all_btn.setCheckable(True)
        self._all_btn.setChecked(True)
        self._all_btn.clicked.connect(self._on_all_periods_clicked)
        bar.addWidget(self._all_btn)

        bar.addWidget(QLabel("  с"))
        self._from_date = QDateEdit(QDate.currentDate().addYears(-1))
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd.MM.yyyy")
        self._from_date.setEnabled(False)
        self._from_date.dateChanged.connect(self._on_custom_date_changed)
        bar.addWidget(self._from_date)

        bar.addWidget(QLabel("по"))
        self._to_date = QDateEdit(QDate.currentDate())
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd.MM.yyyy")
        self._to_date.setEnabled(False)
        self._to_date.dateChanged.connect(self._on_custom_date_changed)
        bar.addWidget(self._to_date)

        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.load_data)
        bar.addWidget(refresh_btn)
        bar.addStretch()
        root.addLayout(bar)

        # ── KPI cards row 1 — основные показатели ────────────────────
        kpi_row = QHBoxLayout()
        self._card_sat   = _KpiCard("Удовлетворённость")
        self._card_conf  = _KpiCard("Конфликтов (в работе)")
        self._card_act   = _KpiCard("Активных клиентов")
        self._card_total = _KpiCard("Всего опросов")
        for card in (self._card_sat, self._card_conf, self._card_act, self._card_total):
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # ── KPI cards row 2 — аналитика по опросам ───────────────────
        fb_label = QLabel("Аналитика по опросам")
        fb_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #555; margin-top: 4px;")
        root.addWidget(fb_label)

        fb_row = QHBoxLayout()
        self._card_sent     = _KpiCard("Направлено опросов")
        self._card_fb_yes   = _KpiCard("Дали обратную связь")
        self._card_fb_no    = _KpiCard("Не дали обратную связь")
        self._card_mis      = _KpiCard("С недопониманием")
        self._card_resolved = _KpiCard("Улажено ситуаций")
        for card in (self._card_sent, self._card_fb_yes, self._card_fb_no,
                     self._card_mis, self._card_resolved):
            fb_row.addWidget(card)
        root.addLayout(fb_row)

        # ── Charts grid ───────────────────────────────────────────────
        charts_grid = QGridLayout()
        charts_grid.setSpacing(8)

        # Trend chart (spans 2 columns on the left)
        self._trend_view = self._make_chart_view()
        charts_grid.addWidget(self._trend_view, 0, 0, 1, 2)

        # Pie chart (right)
        self._pie_view = self._make_chart_view()
        charts_grid.addWidget(self._pie_view, 0, 2, 1, 1)

        charts_grid.setColumnStretch(0, 1)
        charts_grid.setColumnStretch(1, 1)
        charts_grid.setColumnStretch(2, 1)
        charts_grid.setRowStretch(0, 1)

        root.addLayout(charts_grid, stretch=1)

    @staticmethod
    def _make_chart_view() -> QChartView:
        view = QChartView()
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(200)
        return view

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        from_date, to_date = self._date_range()
        log.info("Loading analytics: from=%s to=%s", from_date, to_date)
        self._summary = get_analytics_summary(self._session, from_date, to_date)
        self._refresh_kpi()
        self._refresh_trend()
        self._refresh_pie()
        # Keep chart theme in sync after rebuild
        if self._dark:
            self.set_dark_theme(True)

    def _reapply_series_colors(self) -> None:
        """Re-stamp custom series colours after a theme change overwrites them."""
        # Trend: green bars
        trend_chart = self._trend_view.chart()
        if trend_chart and trend_chart.series():
            bar_series = trend_chart.series()[0]
            if isinstance(bar_series, QBarSeries) and bar_series.barSets():
                bar_series.barSets()[0].setColor(QColor(_GREEN))
        # Pie: use whichever colour list was active when chart was last built
        pie_chart = self._pie_view.chart()
        if pie_chart and pie_chart.series():
            pie_series = pie_chart.series()[0]
            for i, sl in enumerate(pie_series.slices()):
                if i < len(self._pie_colors):
                    sl.setBrush(self._pie_colors[i])

    def _on_all_periods_clicked(self) -> None:
        is_all = self._all_btn.isChecked()
        self._from_date.setEnabled(not is_all)
        self._to_date.setEnabled(not is_all)
        self.load_data()

    def _on_custom_date_changed(self) -> None:
        """Switch off 'Весь период' when user edits date pickers."""
        self._all_btn.setChecked(False)
        self._from_date.setEnabled(True)
        self._to_date.setEnabled(True)
        self.load_data()

    def _date_range(self) -> tuple[date | None, date | None]:
        if self._all_btn.isChecked():
            return None, None
        qf = self._from_date.date()
        qt = self._to_date.date()
        return (
            date(qf.year(), qf.month(), qf.day()),
            date(qt.year(), qt.month(), qt.day()),
        )

    # ------------------------------------------------------------------
    # KPI cards
    # ------------------------------------------------------------------

    def _refresh_kpi(self) -> None:
        s = self._summary
        if s is None:
            return

        # Satisfaction %
        pct = s.satisfaction.satisfaction_pct
        if pct >= 80:
            color = _GREEN
        elif pct >= 60:
            color = _YELLOW
        else:
            color = _RED
        sat_text = f"{pct:.0f}%" if s.satisfaction.total_with_answer else "—"
        self._card_sat.set_value(sat_text, color)

        # Conflicts in progress
        conf = s.conflicts.in_progress
        conf_color = _RED if conf > 0 else _GREEN
        self._card_conf.set_value(str(conf), conf_color)

        # Active clients
        self._card_act.set_value(str(s.active_clients), _BLUE)

        # Total surveys
        self._card_total.set_value(str(s.total_surveys), _GRAY)

        # ── Survey feedback KPIs ──────────────────────────────────────
        fb = s.survey_feedback
        self._card_sent.set_value(str(fb.surveys_sent), _BLUE)
        self._card_fb_yes.set_value(str(fb.feedback_sent), _GREEN)
        self._card_fb_no.set_value(
            str(fb.feedback_not_sent),
            _YELLOW if fb.feedback_not_sent > 0 else _GREEN,
        )
        self._card_mis.set_value(
            str(fb.misunderstanding),
            _RED if fb.misunderstanding > 0 else _GREEN,
        )
        self._card_resolved.set_value(str(fb.resolved), _GREEN)

    # ------------------------------------------------------------------
    # Trend line chart
    # ------------------------------------------------------------------

    def _refresh_trend(self) -> None:
        s = self._summary
        chart = QChart()
        chart.legend().setVisible(False)
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        # Prefer satisfaction trend (richer); fall back to raw survey count
        use_satisfaction = bool(s and s.monthly_trend)
        data_pts = (s.monthly_trend if use_satisfaction else (s.monthly_count if s else []))

        if not data_pts:
            chart.setTitle("Динамика по месяцам — нет данных")
            self._trend_view.setChart(chart)
            return

        chart.setTitle(
            "Динамика удовлетворённости по месяцам (%)"
            if use_satisfaction
            else "Количество контактов по месяцам"
        )

        bar_set = QBarSet("")
        bar_set.setColor(QColor(_GREEN))

        categories = []
        for pt in data_pts:
            categories.append(f"{pt.month:02d}.{pt.year}")
            y_val = pt.satisfaction_pct if use_satisfaction else float(pt.total)
            bar_set.append(y_val)

        series = QBarSeries()
        series.append(bar_set)
        series.setBarWidth(0.6)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)

        axis_y = QValueAxis()
        if use_satisfaction:
            axis_y.setRange(0, 100)
            axis_y.setLabelFormat("%g%%")
            axis_y.setTickCount(6)
        else:
            max_val = max(pt.total for pt in data_pts)
            axis_y.setRange(0, max_val + 1)
            axis_y.setLabelFormat("%d")
            axis_y.setTickCount(min(max_val + 2, 8))

        chart.addSeries(series)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

        self._trend_view.setChart(chart)

    # ------------------------------------------------------------------
    # Pie chart — situation statuses
    # ------------------------------------------------------------------

    def _refresh_pie(self) -> None:
        s = self._summary
        chart = QChart()
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        if s is None:
            chart.setTitle("Статусы ситуаций")
            self._pie_view.setChart(chart)
            return

        conf = s.conflicts
        total_conf = conf.in_progress + conf.resolved + conf.unresolved + conf.closed

        if total_conf > 0:
            # Primary: situation status breakdown
            chart.setTitle("Статусы ситуаций")
            slices_data = [
                ("В работе",  conf.in_progress,  _PIE_COLORS[0]),
                ("Решено",    conf.resolved,      _PIE_COLORS[1]),
                ("Не решено", conf.unresolved,    _PIE_COLORS[2]),
                ("Закрыто",   conf.closed,        _PIE_COLORS[3]),
            ]
            self._pie_colors = list(_PIE_COLORS)
            series = QPieSeries()
            for label, value, color in slices_data:
                if value == 0:
                    continue
                sl = series.append(f"{label}: {value}", value)
                sl.setBrush(color)
                sl.setLabelVisible(True)

        elif s.contact_type_dist:
            # Fallback: contact type distribution (always populated from Excel)
            chart.setTitle("Типы контактов")
            items = sorted(s.contact_type_dist.items(), key=lambda x: -x[1])
            self._pie_colors = [
                _PIE_CONTACT_COLORS[i % len(_PIE_CONTACT_COLORS)]
                for i in range(len(items))
            ]
            series = QPieSeries()
            for i, (label, value) in enumerate(items):
                sl = series.append(f"{label}: {value}", value)
                sl.setBrush(self._pie_colors[i])
                sl.setLabelVisible(True)

        else:
            chart.setTitle("Статусы ситуаций — нет данных")
            self._pie_view.setChart(chart)
            return

        chart.addSeries(series)
        self._pie_view.setChart(chart)

