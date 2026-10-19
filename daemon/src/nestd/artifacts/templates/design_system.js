// Each component in its own shadow root, on the system's background.
var COMPONENT_STYLE =
  ":host { all: initial; display: block; color: inherit; font: 15px/1.5 -apple-system," +
  " BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif; }\n" +
  ".nest-body { container-type: inline-size; container-name: component; }\n";
var components = readData("nest-data");
each(document.querySelectorAll("[data-component]"), function (preview) {
  var html = components[Number(preview.getAttribute("data-component"))];
  mount(preview, typeof html === "string" ? html : "", COMPONENT_STYLE);
});
