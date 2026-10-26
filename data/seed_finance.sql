-- database: scm_finance

DROP TABLE IF EXISTS sku_economics CASCADE;
CREATE TABLE sku_economics (sku_id TEXT PRIMARY KEY, mrp_inr NUMERIC,
  net_price_inr NUMERIC, unit_cost_inr NUMERIC);

INSERT INTO sku_economics (sku_id, mrp_inr, net_price_inr, unit_cost_inr) VALUES
('100231', 150, 95, 55),
('200118', 235, 150, 90),
('300452', 20, 13, 9),
('100377', 180, 115, 68),
('100415', 170, 108, 62),
('100562', 110, 70, 40),
('200247', 115, 73, 43),
('300518', 60, 39, 27),
('300633', 290, 185, 120),
('300741', 285, 195, 160),
('200389', 225, 145, 85),
('300866', 30, 20, 15);
