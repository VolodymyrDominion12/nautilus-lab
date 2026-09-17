/**
 * A lightweight-charts primitive that shades the in-sample and out-of-sample legs of a
 * walk-forward window directly on the time axis.
 *
 * The previous version of the chart drew "IS ends" / "OOS starts" badges in the corner
 * without any boundary on the chart itself, and the chart always showed the last N bars,
 * so the badges could point at a boundary that was not even on screen. A boundary that is
 * not drawn is how an in-sample run gets read as an out-of-sample one.
 */

import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesType,
  Time,
} from 'lightweight-charts';

export interface WindowBands {
  isStart: number | null;
  isEnd: number | null;
  oosStart: number | null;
  oosEnd: number | null;
}

/** Caller-facing shape: unix seconds, any of which may be absent. */
export interface WindowBoundaries {
  isStart?: number | null;
  isEnd?: number | null;
  oosStart?: number | null;
  oosEnd?: number | null;
}

class WindowBandsRenderer implements IPrimitivePaneRenderer {
  private readonly _chart: IChartApi;
  private readonly _bands: WindowBands;

  constructor(chart: IChartApi, bands: WindowBands) {
    this._chart = chart;
    this._bands = bands;
  }

  draw(target: CanvasRenderingTarget2D): void {
    const timeScale = this._chart.timeScale();
    const bands = this._bands;
    const toX = (seconds: number | null): number | null => {
      if (seconds == null) return null;
      return timeScale.timeToCoordinate(seconds as unknown as Time);
    };

    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const isStartX = toX(bands.isStart);
      const isEndX = toX(bands.isEnd);
      const oosStartX = toX(bands.oosStart);
      const oosEndX = toX(bands.oosEnd);

      // Selection window: amber, because parameters were fitted inside it.
      if (isStartX != null && isEndX != null && isEndX > isStartX) {
        context.fillStyle = 'rgba(245, 158, 11, 0.10)';
        context.fillRect(isStartX, 0, isEndX - isStartX, mediaSize.height);
      }
      // Report window: green, because this is the only part that is evidence.
      if (oosStartX != null && oosEndX != null && oosEndX > oosStartX) {
        context.fillStyle = 'rgba(16, 185, 129, 0.10)';
        context.fillRect(oosStartX, 0, oosEndX - oosStartX, mediaSize.height);
      }
      // Embargo gap between the two legs, when there is one.
      if (isEndX != null && oosStartX != null && oosStartX > isEndX) {
        context.fillStyle = 'rgba(107, 114, 128, 0.16)';
        context.fillRect(isEndX, 0, oosStartX - isEndX, mediaSize.height);
      }

      const line = (x: number | null, color: string, label: string) => {
        if (x == null) return;
        context.strokeStyle = color;
        context.lineWidth = 1;
        context.setLineDash([4, 4]);
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, mediaSize.height);
        context.stroke();
        context.setLineDash([]);

        context.font = '10px monospace';
        context.fillStyle = color;
        const width = context.measureText(label).width;
        const left = Math.min(Math.max(x + 4, 2), Math.max(mediaSize.width - width - 4, 2));
        context.fillText(label, left, 12);
      };

      line(isStartX, 'rgba(245, 158, 11, 0.9)', 'IS start');
      if (isEndX != null) line(isEndX, 'rgba(245, 158, 11, 0.9)', 'IS end');
      if (oosStartX != null) line(oosStartX, 'rgba(16, 185, 129, 0.9)', 'OOS start');
      if (oosEndX != null) line(oosEndX, 'rgba(16, 185, 129, 0.9)', 'OOS end');
    });
  }
}

class WindowBandsPaneView implements IPrimitivePaneView {
  private readonly _chart: IChartApi;
  private readonly _state: { bands: WindowBands };

  constructor(chart: IChartApi, state: { bands: WindowBands }) {
    this._chart = chart;
    this._state = state;
  }

  zOrder(): 'bottom' {
    return 'bottom';
  }

  renderer(): IPrimitivePaneRenderer {
    return new WindowBandsRenderer(this._chart, this._state.bands);
  }
}

class WindowBandsPrimitive implements ISeriesPrimitive<Time> {
  private readonly _state: { bands: WindowBands } = {
    bands: { isStart: null, isEnd: null, oosStart: null, oosEnd: null },
  };
  private _views: readonly IPrimitivePaneView[] = [];

  attached(param: { chart: IChartApi; series: ISeriesApi<SeriesType> }): void {
    this._views = [new WindowBandsPaneView(param.chart, this._state)];
  }

  detached(): void {
    this._views = [];
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this._views;
  }

  updateAllViews(): void {
    // Views read `_state` on every render, so there is nothing to recompute here.
  }

  setBands(bands: WindowBands): void {
    this._state.bands = bands;
  }
}

export const createWindowBands = (): WindowBandsPrimitive => new WindowBandsPrimitive();

export type { WindowBandsPrimitive };
