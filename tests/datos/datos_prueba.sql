-- Datos pequeños y conocidos para las pruebas (no son los datos reales de la tienda).

INSERT INTO categories (id, name) VALUES
  (1, 'Gorras'), (2, 'Pantalones'), (3, 'Sudaderas'), (4, 'Zapatos');

INSERT INTO sizes (id, name) VALUES
  (1, 'Ajustable'), (2, '30'), (3, '32'), (4, '34'), (5, 'M'), (6, 'L'), (7, 'XL'), (8, '40'), (9, '41');

INSERT INTO products (id, name, description, price, image, category_id) VALUES
  ('p001', 'Gorra curva · Negra',        'Gorra de visera curva, negra, con cierre ajustable.',      45000, '/img/p001.jpg', 1),
  ('p002', 'Gorra plana · Roja',         'Gorra de visera plana, roja.',                              52000, '/img/p002.jpg', 1),
  ('p003', 'Jean baggy · Azul claro',    'Jean de bota ancha, azul claro, estilo urbano.',           150000, '/img/p003.jpg', 2),
  ('p004', 'Jean recto · Negro',         'Jean de corte recto, negro.',                              140000, '/img/p004.jpg', 2),
  ('p005', 'Sudadera básica · Gris',     'Sudadera de algodón con capucha, gris.',                   185000, '/img/p005.jpg', 3),
  ('p006', 'Sudadera estampada · Negra', 'Sudadera negra con estampado al frente; 100% algodón.',    180000, '/img/p006.jpg', 3),
  ('p007', 'Tenis urbanos · Blancos',    'Tenis blancos de suela gruesa.',                           260000, '/img/p007.jpg', 4),
  ('p008', 'Tenis clásicos · Negros',    'Tenis negros de lona. Tallas por confirmar.',              NULL,   '/img/p008.jpg', 4);

INSERT INTO product_sizes (product_id, size_id, position) VALUES
  ('p001', 1, 0),
  ('p002', 1, 0),
  ('p003', 2, 0), ('p003', 3, 1), ('p003', 4, 2),
  ('p004', 3, 0), ('p004', 4, 1),
  ('p005', 5, 0), ('p005', 6, 1), ('p005', 7, 2),
  ('p006', 5, 0), ('p006', 6, 1),
  ('p007', 8, 0), ('p007', 9, 1);
  -- p008 no tiene tallas a propósito (como los tenis reales pendientes de tallas).
