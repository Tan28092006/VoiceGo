import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import { useApp } from '../context/AppContext';
import '../styles/components/MapView.css';

export default function MapView() {
  const { state } = useApp();
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const layerGroupRef = useRef(null);

  // Initialize map
  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;
    const map = L.map(mapRef.current, {
      center: [state.origin.lat, state.origin.lng],
      zoom: 14,
      zoomControl: false,
      attributionControl: false,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
    }).addTo(map);
    layerGroupRef.current = L.layerGroup().addTo(map);
    mapInstanceRef.current = map;
    return () => { map.remove(); mapInstanceRef.current = null; };
  }, []);

  // Update markers/route when destination / candidates / quote change
  useEffect(() => {
   try {
    const lg = layerGroupRef.current;
    const map = mapInstanceRef.current;
    if (!lg || !map) return;
    lg.clearLayers();

    const origin = state.origin;
    const ok = (v) => typeof v === 'number' && Number.isFinite(v);
    if (!ok(origin.lat) || !ok(origin.lng)) return;

    const pickupIcon = L.divIcon({ className: 'map-pin', html: '<div style="font-size:24px;transform:rotate(-20deg)">🧍</div>', iconSize: [32, 32], iconAnchor: [16, 32] });
    const pin = (color, label) => L.divIcon({
      className: 'map-pin',
      html: `<div style="width:30px;height:30px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${color};box-shadow:0 2px 6px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;">
               <span style="transform:rotate(45deg);color:#fff;font-weight:800;font-size:14px;">${label}</span></div>`,
      iconSize: [30, 30], iconAnchor: [15, 30],
    });

    L.marker([origin.lat, origin.lng], { icon: pickupIcon }).bindPopup(`<b>Điểm đi</b><br>${origin.name}`).addTo(lg);

    const bounds = [[origin.lat, origin.lng]];

    // Candidates (e.g. accessible gates): numbered markers, GREEN = accessible.
    const cands = (state.candidates || []).filter((c) => ok(c.lat) && ok(c.lng));
    if (cands.length) {
      cands.forEach((c, i) => {
        const color = c.accessible ? '#00b14f' : '#f5a623';
        L.marker([c.lat, c.lng], { icon: pin(color, c.accessible ? '♿' : String(i + 1)) })
          .bindPopup(`<b>${c.accessible ? '♿ Dễ tiếp cận' : 'Lựa chọn ' + (i + 1)}</b><br>${c.name}`)
          .addTo(lg);
        bounds.push([c.lat, c.lng]);
      });
      map.fitBounds(bounds, { padding: [50, 50] });
      return;
    }

    const dest = state.destination;
    if (!dest || !ok(dest.lat) || !ok(dest.lng)) return;
    const destColor = dest.accessible ? '#00b14f' : '#ef5350';
    L.marker([dest.lat, dest.lng], { icon: pin(destColor, dest.accessible ? '♿' : '📍') })
      .bindPopup(`<b>${dest.accessible ? '♿ Điểm đến (dễ tiếp cận)' : 'Điểm đến'}</b><br>${dest.name}`)
      .addTo(lg);
    bounds.push([dest.lat, dest.lng]);

    if (state.quote?.geometry) {
      L.polyline(state.quote.geometry, { color: '#00b14f', weight: 5, opacity: 0.8 }).addTo(lg);
    } else {
      L.polyline([[origin.lat, origin.lng], [dest.lat, dest.lng]], { color: '#00b14f', weight: 3, dashArray: '10 6', opacity: 0.6 }).addTo(lg);
    }
    map.fitBounds(bounds, { padding: [40, 40] });
   } catch (err) {
    console.warn('MapView update failed (ignored):', err);
   }
  }, [state.origin, state.destination, state.candidates, state.quote]);

  // The map stage grows/shrinks with a CSS transition; Leaflet must recompute its
  // size (and re-fit) during/after that animation, else tiles render greyed/cut.
  const mapActive = !!(state.destination || state.candidates || state.quote);
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const ok = (v) => typeof v === 'number' && Number.isFinite(v);
    const timers = [80, 260, 440, 620].map((d) => setTimeout(() => {
      try {
        map.invalidateSize();
        const pts = [[state.origin.lat, state.origin.lng]];
        (state.candidates || []).forEach((c) => { if (ok(c.lat) && ok(c.lng)) pts.push([c.lat, c.lng]); });
        const dest = state.destination;
        if (dest && ok(dest.lat) && ok(dest.lng)) pts.push([dest.lat, dest.lng]);
        if (pts.length > 1) map.fitBounds(pts, { padding: [50, 50] });
      } catch (e) {}
    }, d));
    return () => timers.forEach(clearTimeout);
  }, [mapActive]);  // eslint-disable-line react-hooks/exhaustive-deps

  return <div id="route-map" className="route-map" ref={mapRef} aria-hidden="true" />;
}
