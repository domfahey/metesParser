/* Explicit provider adapter test double: this does not exercise WebGL. */
(() => {
  const instances = [];
  class FakeMap {
    constructor(options) {
      this.handlers = {}; this.sources = {}; this.layers = []; this.removed = false;
      this.config = []; this.fit = []; this.style = options.style;
      this.accessToken = options.accessToken;
      instances.push(this);
      setTimeout(() => { this.fire('style.load'); this.fire('load'); this.fire('idle'); }, 0);
    }
    on(event, fn) { (this.handlers[event] ||= []).push(fn); }
    fire(event, data={}) { for (const fn of this.handlers[event] || []) fn(data); }
    setProjection(value) { this.projection = value; }
    setTerrain(value) { this.terrain = value; }
    setPitch(value) { this.pitch = value; }
    setConfigProperty(...args) { this.config.push(args); }
    getSource(id) { return this.sources[id]; }
    addSource(id, value) {
      if (this.sources[id]) throw new Error('duplicate source');
      this.sources[id] = {...value, setData(data) { this.data = data; }};
    }
    getLayer(id) { return this.layers.find(layer => layer.id === id); }
    addLayer(layer) { if (this.getLayer(layer.id)) throw new Error('duplicate layer'); this.layers.push(layer); }
    moveLayer(id, before) { const layer=this.getLayer(id); this.layers=this.layers.filter(item=>item.id!==id); const index=this.layers.findIndex(item=>item.id===before); this.layers.splice(index<0 ? this.layers.length : index,0,layer); }
    setLayoutProperty(id, key, value) { this.getLayer(id).layout[key] = value; }
    setPaintProperty(id, key, value) { this.getLayer(id).paint[key] = value; }
    fitBounds(...args) { this.fit.push(args); }
    setStyle(style) { this.style = style; this.layers = []; this.sources = {}; this.fire('style.load'); this.fire('idle'); }
    areTilesLoaded() { return !this.tilesMissing; }
    queryRenderedFeatures() { return [{properties: {call_id: 'call-one'}}]; }
    remove() { this.removed = true; this.accessToken = ''; this.handlers = {}; }
  }
  window.__maps = instances;
  window.mapboxgl = {Map: FakeMap, supported: () => true, accessToken: ''};
})();
