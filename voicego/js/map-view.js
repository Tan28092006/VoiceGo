/**
 * map-view.js
 * Interactive Leaflet map: shows the trip (pickup -> destination) with a red
 * pickup pin and a green destination pin, plus a rough connecting line.
 * (Real turn-by-turn routing is out of MVP scope — Grab already does that.)
 */
class RouteMap {
    constructor(containerId) {
        this.map = L.map(containerId, {
            zoomControl: true,
            attributionControl: false,
        }).setView([10.8782, 106.8012], 12); // around International University

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
        }).addTo(this.map);

        this.layer = L.layerGroup().addTo(this.map);
        setTimeout(() => this.map.invalidateSize(), 300);
    }

    clear() { this.layer.clearLayers(); }

    _pin(emoji, color) {
        return L.divIcon({
            html: `<div style="background:${color};border:2px solid #fff;border-radius:50% 50% 50% 0;`
                + `transform:rotate(-45deg);width:30px;height:30px;display:flex;align-items:center;`
                + `justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,.45)">`
                + `<span style="transform:rotate(45deg);font-size:14px">${emoji}</span></div>`,
            className: "", iconSize: [30, 30], iconAnchor: [15, 30],
        });
    }

    /** origin/dest: {lat, lng}. Pickup pin = red, destination pin = green. */
    showTrip(origin, dest) {
        this.clear();
        const line = L.polyline(
            [[origin.lat, origin.lng], [dest.lat, dest.lng]],
            { color: "#00c853", weight: 4, opacity: 0.75, dashArray: "6 8", lineCap: "round" }
        );
        this.layer.addLayer(line);
        this.layer.addLayer(L.marker([origin.lat, origin.lng], { icon: this._pin("🧍", "#ef5350") }));
        this.layer.addLayer(L.marker([dest.lat, dest.lng], { icon: this._pin("📍", "#00c853") }));
        this.map.fitBounds(line.getBounds(), { padding: [50, 50], maxZoom: 15 });
        setTimeout(() => this.map.invalidateSize(), 200);
    }
}
