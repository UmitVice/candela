import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { init, use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkPointComponent,
  MarkAreaComponent,
  CanvasRenderer,
]);

export { init };
