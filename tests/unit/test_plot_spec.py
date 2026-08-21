"""sanitize_plot_spec: shared color legends + row-facet headers."""

from switchbay.plots import sanitize_plot_spec


def test_restores_color_legend_when_some_layers_hide_it():
    spec = {
        "layer": [
            {
                "mark": "area",
                "encoding": {
                    "color": {"field": "country", "type": "nominal", "legend": None},
                },
            },
            {
                "mark": "line",
                "encoding": {
                    "color": {"field": "country", "type": "nominal", "title": "Country"},
                    "strokeDash": {"field": "series", "type": "nominal"},
                },
            },
        ],
    }
    sanitize_plot_spec(spec)
    assert "legend" not in spec["layer"][0]["encoding"]["color"]
    assert spec["layer"][1]["encoding"]["color"]["title"] == "Country"


def test_leaves_color_legend_null_when_every_layer_hides_it():
    spec = {
        "layer": [
            {
                "mark": "line",
                "encoding": {"color": {"field": "g", "legend": None}},
            },
            {
                "mark": "point",
                "encoding": {"color": {"field": "g", "legend": None}},
            },
        ],
    }
    sanitize_plot_spec(spec)
    assert spec["layer"][0]["encoding"]["color"]["legend"] is None
    assert spec["layer"][1]["encoding"]["color"]["legend"] is None


def test_lifts_row_facet_headers_to_top():
    spec = {
        "facet": {"row": {"field": "measure", "type": "nominal", "title": None}},
        "spec": {"mark": "line", "encoding": {}},
    }
    sanitize_plot_spec(spec)
    header = spec["facet"]["row"]["header"]
    assert header["labelOrient"] == "top"
    assert header["title"] is None


def test_wraps_long_axis_titles():
    spec = {
        "mark": "point",
        "encoding": {
            "x": {
                "field": "a",
                "title": "TyDiQA Multilingual Question Answering (Direct)",
            },
            "y": {
                "field": "b",
                "axis": {
                    "title": "TyDiQA Multilingual Math (Chain-of-Thought)",
                },
            },
        },
    }
    sanitize_plot_spec(spec)
    xt = spec["encoding"]["x"]["title"]
    yt = spec["encoding"]["y"]["axis"]["title"]
    assert isinstance(xt, list) and len(xt) >= 2
    assert isinstance(yt, list) and len(yt) >= 2
    assert " ".join(yt).startswith("TyDiQA")


def test_does_not_overwrite_author_header():
    spec = {
        "facet": {
            "row": {
                "field": "measure",
                "header": {"labelOrient": "left"},
            },
        },
    }
    sanitize_plot_spec(spec)
    assert spec["facet"]["row"]["header"]["labelOrient"] == "left"
