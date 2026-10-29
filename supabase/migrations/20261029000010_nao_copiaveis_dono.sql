-- 0.32.57 (análise do Claude das 26 carteiras em estudo, relatório 20261029-0956-cfaf; "sim, aplica" do dono no chat em 29/10).
-- Só na conta do dono: (1) liga a regra "nunca copiar lançador de token nem robô de alta frequência" (settings_overrides);
-- (2) tira do estudo e da lista de cópia manual as 24 carteiras marcadas "não copiar" / "tirar do estudo" (ficam DScqtG e dmuXAm).
-- DELETE com WHERE fechado no usuário e nos 24 endereços; nada de outras contas muda.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_nc_on": true, "pump_nc_launch_min": 20, "pump_nc_hft_day": 150, "pump_nc_hold_min_s": 30}'::jsonb,
       'pedido do dono (29/10): nunca copiar lançador de token nem robô de alta frequência'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';

delete from public.study_wallets sw
using public.profiles p
where sw.user_id = p.user_id and lower(p.email) = 'onlineguyat@gmail.com'
  and sw.wallet in ('DQMqCjCiRS8BAkZ2xrJ7QJPqUjoHnRDoPtcXMiEPtSus','4nHt4vaFLw2t9o8Nvp7S6uAn1fKn8Ry6SSYbWM5NQAUc','5YRgrP3mjGzrzirYYN5HAQH19cTYREYwGxW6XRJQUzij','8ekCy2jHHUbW2yeNGFWYJT9Hm9FW7SvZcZK66dSZCDiF','CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o','C8BdBLW1GdnCR86nSpcfRMbshvHqwKq9qSTTdSn71AeV','gVDXhoGbePACvSqN7CZBtQXFW9eyJwsgudPEwSydAkx','GeUnv1jmtviRbR7Gu1JnXSGkUMUgFVBHuEVQVpTaUX1W','JDQKDrc1TQgBRvdFh56tkta5sYcDj1SoP52Eiu64rSrT','CmwFWFQsK2tuNpz3HAbjoxDVSf5miY5vbP425UTRg5Rd','DjM7Tu7whh6P3pGVBfDzwXAx2zaw51GJWrJE3PwtuN7s','4Be9CvxqHW6BYiRAxW9Q3xu1ycTMWaL5z8NX4HR3ha7t','5YPxToTobawvkbn5rkWKYDhZqHf5v6LAtRLNPGiq6U2A','FF3dsqNCpT8gxFGHPzcswEU5GFvERZXMbYTHPQ6iiQro','8ZN71XTdVo8yRovnGLmNgW3Tgniw6A4J3JGLvPD686FP','tejiFSXzD8XSKem6pc6d58bHimCd3gX3SmePs3BAJgi','649ot18fccD6Mc9V4aHWTdoSVCuqAEtg9aWuxBA9cRoU','7jQwHdK771P286Vsn44v7dFVfCH8CzZcL3PZGidbShch','9keCU8mgA23XV8LCgSCJEo4Lspmo9fRBA3MyxJmZKQSp','7gAKiGycmoSKtKWwVeSwqWxfmf9qVUtiyXKi6amTRTM6','AtZ424xr2EskdYUN7y6zCb6ZMD3STkc8CPBYyaG6NvCq','EBx24uAPtaS1SvHwRhKEktSgzaXdiVEyHuSVpAMVwrcD','niggerd597QYedtvjQDVHZTCCGyJrwHNm2i49dkm5zS','4U9s6ktkZVD6W9K5X1RRVG89Mm9ZGznrPhhPhXezNedm');

delete from public.pump_lists pl
using public.profiles p
where pl.user_id = p.user_id and lower(p.email) = 'onlineguyat@gmail.com' and pl.tipo = 'manual'
  and pl.wallet in ('DQMqCjCiRS8BAkZ2xrJ7QJPqUjoHnRDoPtcXMiEPtSus','4nHt4vaFLw2t9o8Nvp7S6uAn1fKn8Ry6SSYbWM5NQAUc','5YRgrP3mjGzrzirYYN5HAQH19cTYREYwGxW6XRJQUzij','8ekCy2jHHUbW2yeNGFWYJT9Hm9FW7SvZcZK66dSZCDiF','CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o','C8BdBLW1GdnCR86nSpcfRMbshvHqwKq9qSTTdSn71AeV','gVDXhoGbePACvSqN7CZBtQXFW9eyJwsgudPEwSydAkx','GeUnv1jmtviRbR7Gu1JnXSGkUMUgFVBHuEVQVpTaUX1W','JDQKDrc1TQgBRvdFh56tkta5sYcDj1SoP52Eiu64rSrT','CmwFWFQsK2tuNpz3HAbjoxDVSf5miY5vbP425UTRg5Rd','DjM7Tu7whh6P3pGVBfDzwXAx2zaw51GJWrJE3PwtuN7s','4Be9CvxqHW6BYiRAxW9Q3xu1ycTMWaL5z8NX4HR3ha7t','5YPxToTobawvkbn5rkWKYDhZqHf5v6LAtRLNPGiq6U2A','FF3dsqNCpT8gxFGHPzcswEU5GFvERZXMbYTHPQ6iiQro','8ZN71XTdVo8yRovnGLmNgW3Tgniw6A4J3JGLvPD686FP','tejiFSXzD8XSKem6pc6d58bHimCd3gX3SmePs3BAJgi','649ot18fccD6Mc9V4aHWTdoSVCuqAEtg9aWuxBA9cRoU','7jQwHdK771P286Vsn44v7dFVfCH8CzZcL3PZGidbShch','9keCU8mgA23XV8LCgSCJEo4Lspmo9fRBA3MyxJmZKQSp','7gAKiGycmoSKtKWwVeSwqWxfmf9qVUtiyXKi6amTRTM6','AtZ424xr2EskdYUN7y6zCb6ZMD3STkc8CPBYyaG6NvCq','EBx24uAPtaS1SvHwRhKEktSgzaXdiVEyHuSVpAMVwrcD','niggerd597QYedtvjQDVHZTCCGyJrwHNm2i49dkm5zS','4U9s6ktkZVD6W9K5X1RRVG89Mm9ZGznrPhhPhXezNedm');
