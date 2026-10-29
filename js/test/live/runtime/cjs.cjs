const { Vaquill } = require("../../../dist/index.cjs");
(async () => {
  const c = new Vaquill();
  const r = await c.credits.balance().withResponse();
  console.log(
    "cjs ok",
    r.meta.status,
    typeof r.data.creditsRemaining,
    Object.keys(require("../../../dist/index.cjs")).length,
    "exports",
  );
})().catch((e) => {
  console.error("cjs FAIL", e.name, e.message);
  process.exit(1);
});
