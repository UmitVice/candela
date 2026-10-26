import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

export function label(
  text: string,
  className = 'obs-label',
  align: 'center' | 'left' | 'right' = 'center',
): CSS2DObject {
  const el = document.createElement('div');
  el.className = className;
  el.textContent = text;
  const object = new CSS2DObject(el);
  object.center.set(align === 'center' ? 0.5 : align === 'left' ? 0 : 1, 0.5);
  return object;
}

export function setLabel(object: CSS2DObject, text: string): void {
  if (object.element.textContent !== text) object.element.textContent = text;
}
