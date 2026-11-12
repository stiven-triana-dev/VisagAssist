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

INSERT INTO colors (id, name) VALUES (1, 'Gris'), (2, 'Negro');
INSERT INTO product_colors (product_id, color_id, position) VALUES ('p005', 1, 0), ('p006', 2, 0);

-- Dos clientes con contraseñas ficticias (el asistente nunca lee esta columna).
INSERT INTO users (id, first_name, last_name, email, password_hash) VALUES
  ('11111111-1111-4111-8111-111111111111', 'Andrés',   'Gómez', 'andres@prueba.test',   'hash-ficticio'),
  ('22222222-2222-4222-8222-222222222222', 'Valentina', 'Ríos', 'valentina@prueba.test', 'hash-ficticio');

INSERT INTO orders (id, number, user_id, status, first_name, last_name, phone, document, department, city, address, payment_method, subtotal, created_at) VALUES
  ('a0000000-0000-4000-8000-000000001001', 1001, '11111111-1111-4111-8111-111111111111', 'entregado',  'Andrés',    'Gómez', '3000000001', '1000000001', 'Cundinamarca', 'Bogotá',   'Calle secreta 1', 'nequi',         150000, NOW() - INTERVAL '40 days'),
  ('a0000000-0000-4000-8000-000000001002', 1002, '11111111-1111-4111-8111-111111111111', 'enviado',    'Andrés',    'Gómez', '3000000001', '1000000001', 'Cundinamarca', 'Bogotá',   'Calle secreta 1', 'contraentrega',  97000, NOW() - INTERVAL '5 days'),
  ('a0000000-0000-4000-8000-000000001003', 1003, '22222222-2222-4222-8222-222222222222', 'nuevo',      'Valentina', 'Ríos',  '3000000002', '1000000002', 'Antioquia',    'Medellín', 'Calle secreta 2', 'tarjeta',       370000, NOW() - INTERVAL '2 days'),
  ('a0000000-0000-4000-8000-000000001004', 1004, '22222222-2222-4222-8222-222222222222', 'cancelado',  'Valentina', 'Ríos',  '3000000002', '1000000002', 'Antioquia',    'Medellín', 'Calle secreta 2', 'tarjeta',       260000, NOW() - INTERVAL '3 days'),
  ('a0000000-0000-4000-8000-000000001005', 1005, NULL,                                   'confirmado', 'Camilo',    'Pérez', '3000000003', '1000000003', 'Valle',        'Cali',     'Calle secreta 3', 'contraentrega', 140000, NOW() - INTERVAL '1 day');

INSERT INTO order_items (order_id, product_id, product_name, size, quantity, unit_price, position) VALUES
  ('a0000000-0000-4000-8000-000000001001', 'p003', 'Jean baggy · Azul claro',  '32',        1, 150000, 0),
  ('a0000000-0000-4000-8000-000000001002', 'p001', 'Gorra curva · Negra',      'Ajustable', 1,  45000, 0),
  ('a0000000-0000-4000-8000-000000001002', 'p002', 'Gorra plana · Roja',       'Ajustable', 1,  52000, 1),
  ('a0000000-0000-4000-8000-000000001003', 'p005', 'Sudadera básica · Gris',   'L',         2, 185000, 0),
  ('a0000000-0000-4000-8000-000000001004', 'p007', 'Tenis urbanos · Blancos',  '41',        1, 260000, 0),
  ('a0000000-0000-4000-8000-000000001005', 'p004', 'Jean recto · Negro',       '32',        1, 140000, 0);
