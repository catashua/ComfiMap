"""Website for comparing shorter walks and cooler walks in the Financial District."""

from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

import router

MONTH_NAMES = {6: "June", 7: "July", 8: "August"}


def hour_label(hour):
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


@st.cache_data
def graphs_on_disk():
    return {key: str(path) for key, path in router.list_graphs().items()}


@st.cache_resource
def network_for(path):
    return router.load_network(Path(path))


def draw_map(routes, selected):
    chosen = routes[selected]
    points = [point for line in chosen["lines"] for point in line]
    if not points:
        st.warning("The walk was found, but it has no line to draw.")
        return
    lat = sum(point[0] for point in points) / len(points)
    lon = sum(point[1] for point in points) / len(points)
    fmap = folium.Map(location=[lat, lon], zoom_start=16, tiles="OpenStreetMap")
    for i, route in enumerate(routes):
        if i == selected:
            continue
        for line in route["lines"]:
            folium.PolyLine(line, color="#9aa0a6", weight=4, opacity=0.8).add_to(fmap)
    for line in chosen["lines"]:
        folium.PolyLine(line, color="#0b6e4f", weight=7, opacity=0.95).add_to(fmap)
    folium.CircleMarker(points[0], radius=7, color="#1a73e8", fill=True, popup="Start").add_to(fmap)
    folium.CircleMarker(points[-1], radius=7, color="#d93025", fill=True, popup="End").add_to(fmap)
    st_folium(fmap, height=520, use_container_width=True, returned_objects=[], key=f"map-{selected}-{len(routes)}")


def main():
    st.set_page_config(page_title="ComfiMap", layout="wide")
    st.title("ComfiMap")
    st.write(
        "Type a starting address and a destination in the Financial District. "
        "The slider moves along walks where getting cooler means walking a bit farther. "
        "The green line is the walk you picked. Gray lines are the other choices."
    )

    available = graphs_on_disk()
    if not available:
        st.error("The walking-network files are missing from the data folder.")
        return

    months = sorted({month for month, _hour in available})
    left, right = st.columns(2)
    origin = left.text_input("Starting address", "Battery Park, New York")
    destination = right.text_input("Destination address", "City Hall, New York")

    month_col, hour_col = st.columns(2)
    default_month = 7 if 7 in months else months[0]
    month = month_col.selectbox(
        "Month",
        months,
        index=months.index(default_month),
        format_func=lambda value: MONTH_NAMES.get(value, str(value)),
    )
    hours = sorted(hour for mon, hour in available if mon == month)
    default_hour = 14 if 14 in hours else hours[len(hours) // 2]
    hour = hour_col.selectbox(
        "Hour",
        hours,
        index=hours.index(default_hour),
        format_func=hour_label,
    )

    if st.button("Find routes", type="primary"):
        try:
            with st.spinner("Looking up the addresses and comparing walks..."):
                start = router.geocode(origin)
                end = router.geocode(destination)
                graph = network_for(available[(month, hour)])
                found = router.routes_between(graph, (start[0], start[1]), (end[0], end[1]))
            st.session_state["routes"] = found
            st.session_state["picked"] = router.knee_index(found)
            st.session_state["names"] = (start[2], end[2])
        except router.RouteError as exc:
            st.session_state.pop("routes", None)
            st.error(str(exc))

    routes = st.session_state.get("routes")
    if not routes:
        st.info("Press **Find routes**. The first search can take a few seconds.")
        return

    names = st.session_state.get("names", ("", ""))
    st.caption(f"From {names[0]}  →  {names[1]}")
    st.caption("Walks are limited to 20% longer than the shortest one. Heat is lower on a more comfortable walk.")
    if len(routes) == 1:
        st.caption("For these two addresses, the shortest walk is already the coolest one in that limit.")

    labels = []
    for i, route in enumerate(routes):
        if i == 0:
            labels.append("Shortest")
        elif i == len(routes) - 1:
            labels.append("Coolest")
        else:
            labels.append(f"+{route['extra_m']:.0f} m")

    picked = st.session_state.get("picked", 0)
    if picked >= len(routes):
        picked = 0
    choice = st.select_slider(
        "Balance distance and heat",
        options=list(range(len(routes))),
        value=picked,
        format_func=lambda i: labels[i],
    )
    st.session_state["picked"] = choice
    route = routes[choice]

    m1, m2, m3 = st.columns(3)
    minutes = route["minutes"]
    walk = "< 1 min" if minutes < 1 else f"{minutes:.0f} min"
    m1.metric("Walk", f"{walk} ({route['distance_m']:.0f} m)")
    m2.metric("Longer than shortest", f"{route['extra_m']:.0f} m")
    if route["heat_saved_pct"] < 0.5:
        m3.metric("Heat vs shortest", "Same")
    else:
        m3.metric("Heat vs shortest", f"{route['heat_saved_pct']:.0f}% lower")

    draw_map(routes, choice)


if __name__ == "__main__":
    main()
