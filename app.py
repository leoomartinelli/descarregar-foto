import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import json
from datetime import date
import shutil
import threading
import time
import psutil
import platform
import subprocess
import rawpy
import imageio
import concurrent.futures
from PIL import Image, ImageOps, ImageFilter, ImageEnhance  # ← adicione ImageFilter, ImageEnhance
import numpy as np  # ← adicione esta linha

GOOGLE_DRIVE_DISPONIVEL = False


# Configurações de tema do CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class RevisorFotosWindow(ctk.CTkToplevel):
    def __init__(self, parent, arquivos, pasta_destino):
        super().__init__(parent)
        self.parent = parent
        self.arquivos_originais = arquivos.copy() # Lista imutável original
        self.arquivos = arquivos.copy()           # Lista ativa de fotos sendo revisadas
        self.descartados = []                     # Pilha de fotos descartadas (para Desfazer)
        self.pasta_destino = pasta_destino
        
        self.current_index = 0
        
        self.title("Revisar e Selecionar Fotos")
        self.geometry("1100x750")
        self.minsize(800, 600)
        
        # Garante foco e captura de eventos na janela de revisão
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        self.after(200, self.focus_force)
        
        # Maximiza a janela após carregar para visualização otimizada
        self.after(150, self.maximizar_janela)
        
        # Caching thread-safe para imagens
        self.cache_imagens = {} # caminho -> PIL.Image
        self.lock_cache = threading.Lock()
        
        self.setup_ui()
        self.bind_events()
        
        # Inicia a thread de pré-carregamento em segundo plano (otimização máxima)
        self.threading_preload = threading.Thread(target=self.preload_loop, daemon=True)
        self.threading_preload.start()
        
        # Exibe a primeira foto
        self.exibir_foto_atual()

    def maximizar_janela(self):
        try:
            if platform.system() == "Windows":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except Exception:
            pass

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Container principal
        self.main_container = ctk.CTkFrame(self)
        self.main_container.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        
        self.main_container.grid_rowconfigure(0, weight=1) # Área da foto
        self.main_container.grid_rowconfigure(1, weight=0) # Barra de ferramentas e status
        self.main_container.grid_columnconfigure(0, weight=1)
        
        # Área de exibição de foto (fundo escuro para destacar a foto)
        self.frame_foto = ctk.CTkFrame(self.main_container, fg_color="#0d0d0d")
        self.frame_foto.grid(row=0, column=0, sticky="nsew", padx=15, pady=(15, 10))
        
        self.lbl_foto = ctk.CTkLabel(self.frame_foto, text="Carregando imagem...", font=ctk.CTkFont(size=16), text_color="gray")
        self.lbl_foto.pack(fill="both", expand=True)
        
        # Evento de redimensionamento dinâmico (com debounce automático)
        self.frame_foto.bind("<Configure>", self.ao_redimensionar)
        
        # Barra de ferramentas na parte inferior
        self.frame_controles = ctk.CTkFrame(self.main_container, height=80)
        self.frame_controles.grid(row=1, column=0, sticky="ew", padx=15, pady=(5, 15))
        
        self.frame_controles.grid_rowconfigure(0, weight=1)
        for i in range(6):
            self.frame_controles.grid_columnconfigure(i, weight=1)
            
        # 1. Botão Anterior
        self.btn_anterior = ctk.CTkButton(
            self.frame_controles, 
            text="◀ Anterior (Seta Esquerda)", 
            font=ctk.CTkFont(size=13),
            command=self.foto_anterior
        )
        self.btn_anterior.grid(row=0, column=0, padx=8, pady=12, sticky="ew")
        
        # 2. Botão Desfazer
        self.btn_desfazer = ctk.CTkButton(
            self.frame_controles, 
            text="↩️ Desfazer (Ctrl+Z)", 
            fg_color="#34495e", 
            hover_color="#2c3e50",
            state="disabled",
            font=ctk.CTkFont(size=13),
            command=self.desfazer_descarte
        )
        self.btn_desfazer.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        
        # 3. Botão Apagar/Descartar (Vermelho em destaque)
        self.btn_descartar = ctk.CTkButton(
            self.frame_controles, 
            text="🗑️ Apagar Foto (Delete)", 
            fg_color="#e74c3c", 
            hover_color="#c0392b",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.descartar_foto
        )
        self.btn_descartar.grid(row=0, column=2, padx=8, pady=12, sticky="ew")
        
        # 4. Botão Próxima
        self.btn_proxima = ctk.CTkButton(
            self.frame_controles, 
            text="Próxima ▶ (Seta Direita)", 
            font=ctk.CTkFont(size=13),
            command=self.proxima_foto
        )
        self.btn_proxima.grid(row=0, column=3, padx=8, pady=12, sticky="ew")
        
        # 5. Label de Status da Revisão
        self.lbl_revisao_status = ctk.CTkLabel(
            self.frame_controles, 
            text="Foto 0/0", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#3498db"
        )
        self.lbl_revisao_status.grid(row=0, column=4, padx=8, pady=12)
        
        # 6. Botão Finalizar (Verde em destaque)
        self.btn_finalizar = ctk.CTkButton(
            self.frame_controles, 
            text="💾 Finalizar Seleção", 
            fg_color="#2ecc71", 
            hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.finalizar_revisao
        )
        self.btn_finalizar.grid(row=0, column=5, padx=8, pady=12, sticky="ew")

    def bind_events(self):
        # Vincula os atalhos recursivamente em todos os widgets (garante 100% de funcionamento independente de onde está o foco)
        self.bind_keys_recursive(self)
        self.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)

    def bind_keys_recursive(self, widget):
        widget.bind("<Left>", lambda e: self.foto_anterior())
        widget.bind("<Right>", lambda e: self.proxima_foto())
        widget.bind("<Delete>", lambda e: self.descartar_foto())
        widget.bind("<BackSpace>", lambda e: self.descartar_foto())
        widget.bind("<Control-z>", lambda e: self.desfazer_descarte())
        widget.bind("<Control-Z>", lambda e: self.desfazer_descarte())
        
        for child in widget.winfo_children():
            self.bind_keys_recursive(child)

    def limpar_eventos_globais(self):
        pass

    def preload_loop(self):
        """Thread de pré-carregamento contínuo em segundo plano para suavidade total ao alternar fotos."""
        while True:
            if not self.arquivos:
                time.sleep(0.5)
                continue
                
            idx_atual = self.current_index
            paths_to_load = []
            
            # Prioridade de pré-carregamento: Atual, Próxima, Anterior, Duas à frente
            if idx_atual < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual])
            if idx_atual + 1 < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual + 1])
            if idx_atual - 1 >= 0:
                paths_to_load.append(self.arquivos[idx_atual - 1])
            if idx_atual + 2 < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual + 2])
                
            for path in paths_to_load:
                with self.lock_cache:
                    in_cache = path in self.cache_imagens
                
                if not in_cache:
                    try:
                        ext = os.path.splitext(path)[1].lower()
                        if ext in ['.cr2', '.nef', '.arw', '.cr3']:
                            with rawpy.imread(path) as raw:
                                # half_size=True é 4 vezes mais rápido e perfeito para renderizar na tela
                                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
                                img_pil = Image.fromarray(rgb)
                        else:
                            img_pil = Image.open(path)
                            img_pil = ImageOps.exif_transpose(img_pil)
                            img_pil.load() # Força a decodificação em segundo plano
                            
                        with self.lock_cache:
                            # Mantém o cache compacto (limite de 12 imagens) para evitar consumo excessivo de RAM
                            if len(self.cache_imagens) > 12:
                                for cached_path in list(self.cache_imagens.keys()):
                                    if cached_path not in self.arquivos:
                                        self.cache_imagens.pop(cached_path, None)
                                    else:
                                        try:
                                            distancia = abs(self.arquivos.index(cached_path) - idx_atual)
                                            if distancia > 4:
                                                self.cache_imagens.pop(cached_path, None)
                                        except ValueError:
                                            self.cache_imagens.pop(cached_path, None)
                                            
                            self.cache_imagens[path] = img_pil
                    except Exception as e:
                        print(f"Erro ao pré-carregar {path}: {e}")
                        
            time.sleep(0.1)

    def obter_imagem_pil(self, path):
        with self.lock_cache:
            if path in self.cache_imagens:
                return self.cache_imagens[path]
                
        # Fallback síncrono caso a thread ainda não tenha carregado
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.cr2', '.nef', '.arw', '.cr3']:
                with rawpy.imread(path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
                    img_pil = Image.fromarray(rgb)
            else:
                img_pil = Image.open(path)
                img_pil = ImageOps.exif_transpose(img_pil)
                img_pil.load()
            
            with self.lock_cache:
                self.cache_imagens[path] = img_pil
            return img_pil
        except Exception as e:
            print(f"Erro ao carregar imagem: {e}")
            return None

    def redimensionar_para_caber(self, img_pil, largura_alvo, altura_alvo):
        if largura_alvo <= 10 or altura_alvo <= 10:
            return None
            
        largura_orig, altura_orig = img_pil.size
        ratio = min(largura_alvo / largura_orig, altura_alvo / altura_orig)
        
        nova_largura = int(largura_orig * ratio)
        nova_altura = int(altura_orig * ratio)
        
        if nova_largura <= 0 or nova_altura <= 0:
            return None
            
        # Otimizado com HAMMING para velocidade e excelente nitidez
        try:
            from PIL.Image import Resampling
            resample_mode = Resampling.HAMMING
        except ImportError:
            resample_mode = Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 2
            
        return img_pil.resize((nova_largura, nova_altura), resample_mode)

    def exibir_foto_atual(self):
        if not self.arquivos:
            self.lbl_foto.configure(image=None, text="Nenhuma foto para exibir.\n\nTodas as fotos foram descartadas ou revisadas!\nClique em 'Finalizar Seleção' para salvar.", font=ctk.CTkFont(size=16))
            self.lbl_revisao_status.configure(text="0 de 0")
            self.btn_descartar.configure(state="disabled")
            self.btn_proxima.configure(state="disabled")
            self.btn_anterior.configure(state="disabled")
            return
            
        if self.current_index >= len(self.arquivos):
            self.current_index = len(self.arquivos) - 1
        if self.current_index < 0:
            self.current_index = 0
            
        path_atual = self.arquivos[self.current_index]
        nome_arquivo = os.path.basename(path_atual)
        
        self.lbl_revisao_status.configure(text=f"Foto {self.current_index + 1}/{len(self.arquivos)}\n{nome_arquivo}")
        
        self.btn_anterior.configure(state="normal" if self.current_index > 0 else "disabled")
        self.btn_proxima.configure(state="normal" if self.current_index < len(self.arquivos) - 1 else "disabled")
        self.btn_descartar.configure(state="normal")
        self.btn_desfazer.configure(state="normal" if self.descartados else "disabled")
        
        self.atualizar_canvas_imagem()

    def ao_redimensionar(self, event):
        """Usa debounce de 50ms para evitar travamento da UI ao arrastar a janela."""
        if hasattr(self, "_resize_after_id"):
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(50, self.atualizar_canvas_imagem)

    def atualizar_canvas_imagem(self):
        if not self.arquivos or self.current_index >= len(self.arquivos):
            return
            
        path_atual = self.arquivos[self.current_index]
        img_pil = self.obter_imagem_pil(path_atual)
        
        if not img_pil:
            self.lbl_foto.configure(image=None, text="Erro ao exibir imagem.")
            return
            
        largura_alvo = self.frame_foto.winfo_width()
        altura_alvo = self.frame_foto.winfo_height()
        
        # Garante valores padrões se a janela não tiver sido renderizada ainda
        if largura_alvo <= 10: largura_alvo = 900
        if altura_alvo <= 10: altura_alvo = 600
        
        img_scaled = self.redimensionar_para_caber(img_pil, largura_alvo - 20, altura_alvo - 20)
        
        if img_scaled:
            self.ctk_img = ctk.CTkImage(
                light_image=img_scaled, 
                dark_image=img_scaled, 
                size=(img_scaled.width, img_scaled.height)
            )
            self.lbl_foto.configure(image=self.ctk_img, text="")

    def foto_anterior(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.exibir_foto_atual()

    def proxima_foto(self):
        if self.current_index < len(self.arquivos) - 1:
            self.current_index += 1
            self.exibir_foto_atual()

    def descartar_foto(self):
        if not self.arquivos:
            return
            
        path_atual = self.arquivos[self.current_index]
        self.arquivos.remove(path_atual)
        self.descartados.append(path_atual)
        
        self.btn_desfazer.configure(state="normal")
        
        if not self.arquivos:
            self.exibir_foto_atual()
            return
            
        if self.current_index >= len(self.arquivos):
            self.current_index = len(self.arquivos) - 1
            
        self.exibir_foto_atual()

    def desfazer_descarte(self):
        if not self.descartados:
            return
            
        recovered_path = self.descartados.pop()
        
        # Encontra a posição original relativa na lista
        orig_idx = self.arquivos_originais.index(recovered_path)
        
        insert_idx = 0
        for i, active_path in enumerate(self.arquivos):
            active_orig_idx = self.arquivos_originais.index(active_path)
            if active_orig_idx > orig_idx:
                insert_idx = i
                break
        else:
            insert_idx = len(self.arquivos)
            
        self.arquivos.insert(insert_idx, recovered_path)
        self.current_index = insert_idx
        
        self.btn_desfazer.configure(state="normal" if self.descartados else "disabled")
        self.exibir_foto_atual()

    def finalizar_revisao(self):
        total_descartados = len(self.descartados)
        if total_descartados > 0:
            confirmar = messagebox.askyesno(
                "Confirmar Exclusão", 
                f"Você marcou {total_descartados} foto(s) para exclusão.\n\n"
                "Elas serão apagadas permanentemente do computador.\n"
                "Deseja continuar?"
            )
            if not confirmar:
                return
                
            # Oculta a janela de seleção imediatamente para melhor UX e libera o foco
            self.withdraw()
            self.grab_release()
            
            sucessos = 0
            erros = 0
            for path in self.descartados:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                        sucessos += 1
                except Exception as e:
                    print(f"Erro ao deletar {path}: {e}")
                    erros += 1
            
            self.parent.arquivos_transferidos = self.arquivos.copy()
            self.parent.registrar_historico(total_selecionadas=len(self.arquivos))
            
            mensagem = f"Limpeza concluída! {sucessos} foto(s) foram apagadas."
            if erros > 0:
                mensagem += f"\n(Erro ao apagar {erros} foto(s).)"
            messagebox.showinfo("Sucesso", mensagem)
        else:
            # Oculta a janela de seleção imediatamente para melhor UX e libera o foco
            self.withdraw()
            self.grab_release()
            messagebox.showinfo("Concluído", "Revisão terminada! Nenhuma foto foi apagada.")
            self.parent.registrar_historico(total_selecionadas=len(self.arquivos))
            
        self.limpar_eventos_globais()
        self.destroy()
        
        # Garante que os botões na janela principal sejam reativados corretamente
        self.parent.btn_selecionar.configure(state="normal")
        self.parent.btn_abrir.configure(state="normal")

        # Abre a pasta contendo as fotos finais selecionadas
        self.parent.abrir_pasta()

    def ao_fechar_janela(self):
        resposta = messagebox.askyesnocancel(
            "Finalizar Seleção", 
            "Deseja salvar suas escolhas e finalizar a revisão?\n\n"
            "- 'Sim': Aplica as exclusões permanentemente e abre a pasta.\n"
            "- 'Não': Fecha sem salvar (mantém todas as fotos no computador).\n"
            "- 'Cancelar': Continua na tela de revisão de fotos."
        )
        if resposta is True:
            self.finalizar_revisao()
        elif resposta is False:
            self.limpar_eventos_globais()
            self.parent.btn_selecionar.configure(state="normal")
            self.parent.btn_abrir.configure(state="normal")
            self.grab_release()
            self.destroy()


class HistoricoDadosWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Histórico e Dados de Descarregamento")
        self.geometry("800x550")
        self.minsize(800, 550)
        
        # Foco e grab_set seguro
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        
        self.caminho_hist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historico_downloads.json")
        self.setup_ui()
        self.carregar_e_exibir()

    def setup_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        
        self.frame_header.grid_columnconfigure(0, weight=1)
        self.frame_header.grid_columnconfigure(1, weight=0)
        
        self.lbl_titulo = ctk.CTkLabel(
            self.frame_header, 
            text="Histórico Recente de Transferências", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=0, sticky="w")
        
        self.btn_limpar = ctk.CTkButton(
            self.frame_header, 
            text="🗑️ Limpar Histórico", 
            width=120,
            height=28,
            fg_color="#e74c3c",
            hover_color="#c0392b",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.limpar_historico
        )
        self.btn_limpar.grid(row=0, column=1, sticky="e")
        
        # Scrollable Frame para o histórico
        self.scroll_lista = ctk.CTkScrollableFrame(self, fg_color="#1a1a1a")
        self.scroll_lista.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        
        # Botão Fechar no rodapé
        self.btn_fechar = ctk.CTkButton(
            self, 
            text="Fechar", 
            height=32,
            font=ctk.CTkFont(weight="bold"),
            command=self.fechar_janela
        )
        self.btn_fechar.grid(row=2, column=0, padx=20, pady=15, sticky="ew")

    def carregar_e_exibir(self):
        for widget in self.scroll_lista.winfo_children():
            widget.destroy()
            
        historico = []
        if os.path.exists(self.caminho_hist):
            try:
                with open(self.caminho_hist, 'r', encoding='utf-8') as f:
                    historico = json.load(f)
            except Exception:
                pass
                
        if not historico:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_lista, 
                text="Nenhum registro de descarregamento encontrado.", 
                text_color="gray",
                font=ctk.CTkFont(size=13)
            )
            lbl_vazio.pack(pady=40)
            return
            
        for item in reversed(historico):
            frame_item = ctk.CTkFrame(self.scroll_lista, fg_color="#2b2b2b")
            frame_item.pack(fill="x", pady=6, padx=5)
            
            data_formatada = item.get("data", "")
            try:
                partes = data_formatada.split("-")
                if len(partes) == 3:
                    data_formatada = f"{partes[2]}/{partes[1]}/{partes[0]}"
            except Exception:
                pass
                
            texto_info = (
                f"📅 {data_formatada} às {item.get('hora', '')}\n"
                f"👤 Fotógrafo: {item.get('fotografo', '')}\n"
                f"📥 Copiadas: {item.get('descarregadas', 0)}  |  ✅ Selecionadas: {item.get('selecionadas', 0)}\n"
                f"📁 Caminho: {item.get('destino', '')}"
            )
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=texto_info, 
                font=ctk.CTkFont(size=12),
                justify="left",
                anchor="w"
            )
            lbl_info.pack(side="left", padx=15, pady=10, fill="x", expand=True)
            
            btn_abrir_pasta = ctk.CTkButton(
                frame_item, 
                text="📁 Abrir Pasta", 
                width=100, 
                height=28,
                fg_color="#1f538d", 
                hover_color="#14375e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda p=item.get('destino', ''): self.abrir_pasta_historico(p)
            )
            btn_abrir_pasta.pack(side="right", padx=15, pady=10)

    def abrir_pasta_historico(self, pasta):
        if not pasta:
            return
        if os.path.exists(pasta):
            if platform.system() == "Windows":
                os.startfile(pasta)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", pasta])
            else:
                subprocess.Popen(["xdg-open", pasta])
        else:
            messagebox.showwarning("Pasta Não Encontrada", f"A pasta '{pasta}' não existe ou foi movida/deletada.")

    def limpar_historico(self):
        confirmar = messagebox.askyesno("Limpar Histórico", "Deseja realmente limpar todo o histórico de dados?")
        if confirmar:
            try:
                if os.path.exists(self.caminho_hist):
                    os.remove(self.caminho_hist)
                self.carregar_e_exibir()
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível limpar o histórico: {e}")

    def fechar_janela(self):
        self.grab_release()
        self.destroy()


class ConfiguradorDriveWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Configurações do Líder - Pastas")
        self.geometry("750x650")
        self.minsize(750, 650)
        
        # Foco e grab_set seguro
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        
        self.caminho_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_pastas.json")
        self.pastas = []
        self.pastas_local = []
        self.carregar_config()
        
        self.setup_ui()
        self.atualizar_lista_local()

    def carregar_config(self):
        if os.path.exists(self.caminho_config):
            try:
                with open(self.caminho_config, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, dict) and "data" in dados:
                        hoje = date.today().isoformat()
                        if dados["data"] == hoje:
                            self.pastas = dados.get("pastas", [])
                            self.pastas_local = dados.get("pastas_local", [])
                            return
            except Exception as e:
                print(f"Erro ao carregar JSON: {e}")
        self.pastas = []
        self.pastas_local = []

    def salvar_config(self):
        try:
            hoje = date.today().isoformat()
            dados = {
                "data": hoje,
                "pastas": self.pastas,
                "pastas_local": self.pastas_local
            }
            with open(self.caminho_config, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar as configurações: {e}")
            return False

    def setup_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Título
        self.lbl_titulo = ctk.CTkLabel(
            self, 
            text="Configurações do Líder - Pastas Locais Pré-definidas", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=0, pady=(15, 5), padx=20, sticky="w")
        
        # Lista de Pastas do Computador (Scrollable Frame)
        self.scroll_lista_local = ctk.CTkScrollableFrame(self, fg_color="#1a1a1a")
        self.scroll_lista_local.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        
        # Container de adição de nova pasta do Computador
        self.frame_adicionar_local = ctk.CTkFrame(self, fg_color="#242424")
        self.frame_adicionar_local.grid(row=2, column=0, padx=20, pady=(5, 10), sticky="ew")
        
        self.frame_adicionar_local.grid_columnconfigure(0, weight=1)
        self.frame_adicionar_local.grid_columnconfigure(1, weight=0)
        
        self.lbl_add_titulo_local = ctk.CTkLabel(
            self.frame_adicionar_local, 
            text="Adicionar Nova Pasta do Computador", 
            font=ctk.CTkFont(weight="bold")
        )
        self.lbl_add_titulo_local.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 5), sticky="w")
        
        # Sub-frame para o caminho da pasta
        self.frame_caminho_local = ctk.CTkFrame(self.frame_adicionar_local, fg_color="transparent")
        self.frame_caminho_local.grid(row=1, column=0, columnspan=2, padx=15, pady=5, sticky="ew")
        self.frame_caminho_local.grid_columnconfigure(0, weight=1)
        
        self.entry_caminho_local = ctk.CTkEntry(
            self.frame_caminho_local, 
            placeholder_text="Caminho da pasta no computador..."
        )
        self.entry_caminho_local.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.btn_procurar_local = ctk.CTkButton(
            self.frame_caminho_local, 
            text="Procurar...", 
            width=100,
            command=self.procurar_caminho_local
        )
        self.btn_procurar_local.grid(row=0, column=1, sticky="ew")
        
        # Nome personalizado
        self.entry_nome_local = ctk.CTkEntry(
            self.frame_adicionar_local, 
            placeholder_text="Nome de Exibição (Opcional - preenchido automaticamente)"
        )
        self.entry_nome_local.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_add_local = ctk.CTkButton(
            self.frame_adicionar_local, 
            text="Adicionar", 
            fg_color="#2ecc71", 
            hover_color="#27ae60",
            font=ctk.CTkFont(weight="bold"),
            command=self.adicionar_pasta_local
        )
        self.btn_add_local.grid(row=2, column=1, padx=15, pady=5, sticky="ew")

        # Botão Salvar e Fechar no rodapé
        self.btn_salvar_fechar = ctk.CTkButton(
            self, 
            text="Salvar e Fechar", 
            height=32,
            font=ctk.CTkFont(weight="bold"),
            command=self.salvar_e_fechar
        )
        self.btn_salvar_fechar.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")



    def procurar_caminho_local(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta do computador")
        if pasta:
            self.entry_caminho_local.delete(0, 'end')
            self.entry_caminho_local.insert(0, pasta)
            # Preenche automaticamente o nome com o nome da pasta selecionada
            nome_pasta = os.path.basename(pasta.rstrip("/\\"))
            if not nome_pasta:
                nome_pasta = pasta
            self.entry_nome_local.delete(0, 'end')
            self.entry_nome_local.insert(0, nome_pasta)

    def adicionar_pasta_local(self):
        caminho = self.entry_caminho_local.get().strip()
        if not caminho:
            messagebox.showwarning("Aviso", "Selecione ou digite o caminho da pasta no computador!")
            return
            
        nome = self.entry_nome_local.get().strip()
        if not nome:
            nome = os.path.basename(caminho)
            if not nome:
                nome = caminho
                
        self.pastas_local.append({
            "nome": nome,
            "caminho": caminho
        })
        
        self.entry_caminho_local.delete(0, 'end')
        self.entry_nome_local.delete(0, 'end')
        
        self.atualizar_lista_local()

    def remover_pasta_local(self, index):
        if 0 <= index < len(self.pastas_local):
            del self.pastas_local[index]
            self.atualizar_lista_local()

    def atualizar_lista_local(self):
        for widget in self.scroll_lista_local.winfo_children():
            widget.destroy()
            
        if not self.pastas_local:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_lista_local, 
                text="Nenhuma pasta local configurada. Adicione uma pasta abaixo.", 
                text_color="gray"
            )
            lbl_vazio.pack(pady=30)
            return
            
        for i, item in enumerate(self.pastas_local):
            frame_item = ctk.CTkFrame(self.scroll_lista_local, fg_color="#2b2b2b", cursor="hand2")
            frame_item.pack(fill="x", pady=4, padx=5)
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=f"📁 {item['nome']}\nCaminho: {item['caminho']}", 
                font=ctk.CTkFont(size=12),
                justify="left",
                anchor="w",
                cursor="hand2"
            )
            lbl_info.pack(side="left", padx=10, pady=6, fill="x", expand=True)
            
            # Clique para abrir a pasta local
            frame_item.bind("<Button-1>", lambda event, caminho=item['caminho']: self.abrir_pasta_local(caminho))
            lbl_info.bind("<Button-1>", lambda event, caminho=item['caminho']: self.abrir_pasta_local(caminho))
            
            btn_remove = ctk.CTkButton(
                frame_item, 
                text="Remover", 
                width=60, 
                height=24,
                fg_color="#e74c3c", 
                hover_color="#c0392b",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda idx=i: self.remover_pasta_local(idx)
            )
            btn_remove.pack(side="right", padx=(5, 10), pady=6)

            btn_abrir = ctk.CTkButton(
                frame_item, 
                text="Abrir Pasta", 
                width=80, 
                height=24,
                fg_color="#1f538d", 
                hover_color="#14375e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda caminho=item['caminho']: self.abrir_pasta_local(caminho)
            )
            btn_abrir.pack(side="right", padx=(10, 5), pady=6)

    def salvar_e_fechar(self):
        if self.salvar_config():
            self.parent.recarregar_combo_destino()
            self.grab_release()
            self.destroy()

    def abrir_pasta_local(self, pasta):
        if not pasta:
            return
        if os.path.exists(pasta):
            try:
                if platform.system() == "Windows":
                    os.startfile(pasta)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", pasta])
                else:
                    subprocess.Popen(["xdg-open", pasta])
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível abrir a pasta: {e}")
        else:
            messagebox.showwarning("Pasta Não Encontrada", f"A pasta '{pasta}' não existe ou foi movida/deletada.")


class ImportadorFotosApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Descarregador de Fotos - Ministério")
        self.geometry("700x820")
        self.resizable(True, True)
        self.minsize(700, 820)

        self.destino_path = ctk.StringVar()
        self.cartao_detectado = False
        self.origem_manual = False      # Flag para indicar seleção manual de pasta
        self.drive_path = ""
        self.checkboxes_pastas = []
        self.arquivos_transferidos = [] # Guarda o caminho de todas as fotos transferidas com sucesso
        
        # Carrega configuração de pastas locais para o líder
        self.caminho_config_pastas = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_pastas.json")
        self.pastas_local = self.carregar_config_pastas_local()
        
        self.setup_ui()
        
        self.monitor_thread = threading.Thread(target=self.monitorar_cartao, daemon=True)
        self.monitor_thread.start()

    def carregar_config_pastas_local(self):
        if os.path.exists(self.caminho_config_pastas):
            try:
                with open(self.caminho_config_pastas, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, dict) and "data" in dados:
                        hoje = date.today().isoformat()
                        if dados["data"] == hoje:
                            return dados.get("pastas_local", [])
            except Exception as e:
                print(f"Erro ao carregar pastas locais: {e}")
        return []

    def abrir_configurador_drive(self):
        self.janela_config = ConfiguradorDriveWindow(self)

    def abrir_historico_dados(self):
        self.janela_dados = HistoricoDadosWindow(self)

    def registrar_historico(self, total_selecionadas=None):
        try:
            caminho_hist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historico_downloads.json")
            historico = []
            if os.path.exists(caminho_hist):
                try:
                    with open(caminho_hist, 'r', encoding='utf-8') as f:
                        historico = json.load(f)
                except Exception:
                    pass
            
            # Se for uma atualização de revisão
            if total_selecionadas is not None and historico:
                # Procura a última entrada deste fotógrafo e destino para atualizar
                for entry in reversed(historico):
                    if entry.get("fotografo") == self.sessao_fotografo and entry.get("destino") == self.sessao_destino:
                        entry["selecionadas"] = total_selecionadas
                        break
            else:
                # Nova entrada de descarregamento
                nome_fotografo = self.entry_nome.get().strip()
                destino = self.destino_path.get()
                if self.criar_pasta_fotografo_var.get():
                    destino = os.path.join(destino, nome_fotografo)
                
                # Armazena na sessão
                self.sessao_fotografo = nome_fotografo
                self.sessao_destino = destino
                
                total_descarregadas = len(self.arquivos_transferidos)
                
                hoje = date.today().isoformat()
                hora = time.strftime("%H:%M:%S")
                
                nova_entrada = {
                    "data": hoje,
                    "hora": hora,
                    "fotografo": nome_fotografo,
                    "descarregadas": total_descarregadas,
                    "selecionadas": total_descarregadas, # Inicialmente todas
                    "destino": destino
                }
                historico.append(nova_entrada)
                
            with open(caminho_hist, 'w', encoding='utf-8') as f:
                json.dump(historico, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao registrar histórico: {e}")



    def recarregar_combo_destino(self):
        self.pastas_local = self.carregar_config_pastas_local()
        valores_menu = []
        for p in self.pastas_local:
            valores_menu.append(p['nome'])
        valores_menu.append("Escolher pasta personalizada...")
        self.combo_destino.configure(values=valores_menu)
        
        opcao_atual = self.combo_destino_var.get()
        if opcao_atual not in valores_menu:
            if self.pastas_local:
                self.combo_destino_var.set(self.pastas_local[0]['nome'])
                self.destino_path.set(self.pastas_local[0]['caminho'])
            else:
                self.combo_destino_var.set("Escolher pasta personalizada...")
                self.destino_path.set("")
        else:
            if opcao_atual != "Escolher pasta personalizada...":
                for p in self.pastas_local:
                    if p['nome'] == opcao_atual:
                        self.destino_path.set(p['caminho'])
                        break

    def ao_alterar_destino_combo(self, opcao):
        if opcao == "Escolher pasta personalizada...":
            self.selecionar_destino()
        else:
            for p in self.pastas_local:
                if p['nome'] == opcao:
                    self.destino_path.set(p['caminho'])
                    break

    def setup_ui(self):
        # Frame do Cabeçalho para alinhar o título e os botões Novo e Config no topo
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.pack(fill="x", padx=40, pady=(8, 1))
        
        self.frame_header.grid_columnconfigure(0, weight=0)
        self.frame_header.grid_columnconfigure(1, weight=1)
        self.frame_header.grid_columnconfigure(2, weight=0)

        # Container esquerdo do Cabeçalho para os botões Novo e Config
        self.frame_header_botoes = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        self.frame_header_botoes.grid(row=0, column=0, sticky="w")

        # Botão Novo Descarregamento no canto superior esquerdo
        self.btn_novo = ctk.CTkButton(
            self.frame_header_botoes, 
            text="🔄 Novo", 
            font=ctk.CTkFont(size=11, weight="bold"), 
            height=26, 
            width=70,
            fg_color="#27ae60", 
            hover_color="#219653", 
            command=self.novo_descarregamento
        )
        self.btn_novo.pack(side="left", padx=(0, 5))

        # Botão de Configuração do Líder
        self.btn_config = ctk.CTkButton(
            self.frame_header_botoes, 
            text="⚙️ Config", 
            font=ctk.CTkFont(size=11, weight="bold"), 
            height=26, 
            width=70,
            fg_color="#34495e", 
            hover_color="#2c3e50", 
            command=self.abrir_configurador_drive
        )
        self.btn_config.pack(side="left")

        # Título centralizado
        self.lbl_titulo = ctk.CTkLabel(
            self.frame_header, 
            text="Descarregador de Fotos", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=1, sticky="nsew")

        # Container direito do Cabeçalho para o botão Dados (alinhado à direita)
        self.frame_header_dados = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        self.frame_header_dados.grid(row=0, column=2, sticky="e")

        # Spacer para empurrar o botão Dados e balancear a largura com o lado esquerdo (145px total)
        self.spacer_dados = ctk.CTkLabel(self.frame_header_dados, text="", width=75)
        self.spacer_dados.pack(side="left")

        # Botão de Dados/Métricas
        self.btn_dados = ctk.CTkButton(
            self.frame_header_dados, 
            text="📊 Dados", 
            font=ctk.CTkFont(size=11, weight="bold"), 
            height=26, 
            width=70,
            fg_color="#34495e", 
            hover_color="#2c3e50", 
            command=self.abrir_historico_dados
        )
        self.btn_dados.pack(side="right")

        self.lbl_status = ctk.CTkLabel(self, text="Aguardando inserção do Cartão SD...", text_color="orange", font=ctk.CTkFont(size=12))
        self.lbl_status.pack(pady=(0, 4))

        self.lbl_nome = ctk.CTkLabel(self, text="Nome do Fotógrafo:")
        self.lbl_nome.pack(anchor="w", padx=40)
        self.entry_nome = ctk.CTkEntry(self, width=520, height=28, placeholder_text="Ex: JoaoSilva")
        self.entry_nome.pack(pady=(0, 4), padx=40, fill="x")

        # Container para a label e o botão de seleção manual
        self.frame_lbl_pastas = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_lbl_pastas.pack(fill="x", padx=40, pady=(0, 2))

        self.lbl_pastas = ctk.CTkLabel(self.frame_lbl_pastas, text="Pastas no Cartão SD:")
        self.lbl_pastas.pack(side="left")

        self.btn_manual = ctk.CTkButton(
            self.frame_lbl_pastas, 
            text="📂 Origem Manual", 
            height=20, 
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#34495e",
            hover_color="#2c3e50",
            command=self.selecionar_origem_manual
        )
        self.btn_manual.pack(side="right")
        
        self.frame_pastas = ctk.CTkScrollableFrame(self, width=500, height=60)
        self.frame_pastas.pack(pady=(0, 4), padx=40, fill="both", expand=True)
        
        self.lbl_vazio = ctk.CTkLabel(self.frame_pastas, text="Nenhum cartão detectado.")
        self.lbl_vazio.pack(pady=15)

        self.lbl_destino = ctk.CTkLabel(self, text="Pasta de Destino no Computador:")
        self.lbl_destino.pack(anchor="w", padx=40)
        
        self.frame_destino_combo = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_destino_combo.pack(fill="x", padx=40, pady=(0, 2))
        
        valores_destino = []
        for p in self.pastas_local:
            valores_destino.append(p['nome'])
        valores_destino.append("Escolher pasta personalizada...")
        
        if self.pastas_local:
            opcao_inicial = self.pastas_local[0]['nome']
            self.destino_path.set(self.pastas_local[0]['caminho'])
        else:
            opcao_inicial = "Escolher pasta personalizada..."
            self.destino_path.set("")
            
        self.combo_destino_var = ctk.StringVar(value=opcao_inicial)
        self.combo_destino = ctk.CTkOptionMenu(
            self.frame_destino_combo, 
            values=valores_destino,
            variable=self.combo_destino_var,
            command=self.ao_alterar_destino_combo,
            width=400,
            height=28
        )
        self.combo_destino.pack(side="left", padx=(0, 10), fill="x", expand=True)
        
        self.btn_destino = ctk.CTkButton(
            self.frame_destino_combo, 
            text="Procurar...", 
            width=110, 
            height=28, 
            command=self.selecionar_destino
        )
        self.btn_destino.pack(side="left")

        # Exibe o caminho completo selecionado (somente leitura)
        self.entry_destino = ctk.CTkEntry(
            self, 
            textvariable=self.destino_path, 
            width=520, 
            height=28, 
            state="readonly"
        )
        self.entry_destino.pack(pady=(2, 4), padx=40, fill="x")



        self.criar_pasta_fotografo_var = ctk.BooleanVar(value=True)
        self.chk_criar_pasta_fotografo = ctk.CTkCheckBox(self, text="Criar subpasta local com o nome do fotógrafo", variable=self.criar_pasta_fotografo_var)
        self.chk_criar_pasta_fotografo.pack(anchor="w", padx=40, pady=(0, 4))

        self.lbl_progresso = ctk.CTkLabel(self, text="Progresso: 0%")
        self.lbl_progresso.pack(anchor="w", padx=40)
        self.progressbar = ctk.CTkProgressBar(self, width=520, height=8)
        self.progressbar.pack(pady=(1, 6), padx=40, fill="x")
        self.progressbar.set(0)

        # Botão principal de transferência
        self.frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes.pack(pady=(2, 1), padx=40, fill="x")

        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes, 
            text="Iniciar Transferência", 
            font=ctk.CTkFont(size=13, weight="bold"), 
            height=36, 
            fg_color="green", 
            hover_color="darkgreen", 
            command=self.iniciar_transferencia
        )
        self.btn_iniciar.pack(fill="x", expand=True)

        # Botões secundários posicionados lado a lado abaixo da transferência
        self.frame_botoes_secundarios = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes_secundarios.pack(pady=(1, 4), padx=40, fill="x")

        self.btn_selecionar = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="🔍 Selecionar / Revisar Fotos", 
            height=36, 
            font=ctk.CTkFont(size=12, weight="bold"), 
            fg_color="#1f538d", 
            hover_color="#14375e", 
            command=self.abrir_revisor, 
            state="disabled"
        )
        self.btn_selecionar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_abrir = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="📁 Abrir Pasta", 
            height=36, 
            font=ctk.CTkFont(size=12), 
            command=self.abrir_pasta, 
            state="disabled"
        )
        self.btn_abrir.pack(side="right", fill="x", expand=True)



    def monitorar_cartao(self):
        # Mapeia device -> mountpoint para os drives inicialmente montados
        drives_iniciais = {p.device: p.mountpoint for p in psutil.disk_partitions() if p.mountpoint}
        while True:
            time.sleep(1.5)
            drives_atuais = {p.device: p.mountpoint for p in psutil.disk_partitions() if p.mountpoint}
            novos_devices = [d for d in drives_atuais if d not in drives_iniciais]
            
            if novos_devices:
                device_novo = novos_devices[0]
                mountpoint_novo = drives_atuais[device_novo]
                
                self.drive_path = mountpoint_novo
                self.cartao_detectado = True
                self.origem_manual = False
                
                # Atualiza a UI de forma segura na thread principal
                self.after(0, lambda path=self.drive_path: self.atualizar_ui_cartao_detectado(path))
                
                # Abre a pasta DCIM (ou raiz) do cartão no gerenciador de arquivos do sistema
                self.abrir_pasta_dcim(self.drive_path)
                
                drives_iniciais = drives_atuais
            elif len(drives_atuais) < len(drives_iniciais):
                # Se o usuário escolheu uma origem manual, ignoramos a remoção de outros drives
                if self.origem_manual:
                    drives_iniciais = drives_atuais
                else:
                    self.drive_path = ""
                    self.cartao_detectado = False
                    self.after(0, self.atualizar_ui_cartao_removido)
                    drives_iniciais = drives_atuais

    def abrir_pasta_dcim(self, drive):
        caminho_dcim = os.path.join(drive, "DCIM")
        alvo = caminho_dcim if os.path.exists(caminho_dcim) and os.path.isdir(caminho_dcim) else drive
        if os.path.exists(alvo) and os.path.isdir(alvo):
            try:
                if platform.system() == "Windows":
                    os.startfile(alvo)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", alvo])
                else:
                    subprocess.Popen(["xdg-open", alvo])
            except Exception as e:
                print(f"Erro ao abrir pasta {alvo}: {e}")

    def selecionar_origem_manual(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta de origem das fotos (Cartão ou Pasta)")
        if pasta:
            self.drive_path = pasta
            self.cartao_detectado = True
            self.origem_manual = True
            self.atualizar_ui_cartao_detectado(pasta, e_manual=True)

    def atualizar_ui_cartao_detectado(self, drive, e_manual=False):
        if e_manual:
            self.lbl_status.configure(text=f"Origem Manual Selecionada: {drive}", text_color="#3498db")
        else:
            self.lbl_status.configure(text=f"Cartão Detectado: {drive}", text_color="lightgreen")
            
        for widget in self.frame_pastas.winfo_children():
            widget.destroy()
        self.checkboxes_pastas.clear()
        
        try:
            pastas_encontradas = []
            
            # Opção de importar a pasta raiz inteira de forma direta
            var_raiz = ctk.StringVar(value="")
            cb_raiz = ctk.CTkCheckBox(
                self.frame_pastas, 
                text="[Pasta Completa] Importar tudo desta pasta principal", 
                variable=var_raiz, 
                onvalue=".", 
                offvalue="",
                text_color="#3498db" if e_manual else "#2ecc71"
            )
            cb_raiz.pack(anchor="w", pady=5, padx=10)
            self.checkboxes_pastas.append(var_raiz)
            
            caminho_dcim = os.path.join(drive, "DCIM")
            
            if os.path.exists(caminho_dcim) and os.path.isdir(caminho_dcim):
                for sub_item in os.listdir(caminho_dcim):
                    caminho_sub = os.path.join(caminho_dcim, sub_item)
                    if os.path.isdir(caminho_sub):
                        pastas_encontradas.append(f"DCIM/{sub_item}")
            else:
                for item in os.listdir(drive):
                    caminho_completo = os.path.join(drive, item)
                    if os.path.isdir(caminho_completo) and not item.startswith('$'):
                        pastas_encontradas.append(item)

            for pasta in pastas_encontradas:
                var = ctk.StringVar(value="")
                cb = ctk.CTkCheckBox(self.frame_pastas, text=pasta, variable=var, onvalue=pasta, offvalue="")
                cb.pack(anchor="w", pady=5, padx=10)
                self.checkboxes_pastas.append(var)
                
        except Exception as e:
            print(f"Erro ao ler cartão: {e}")

    def atualizar_ui_cartao_removido(self):
        self.lbl_status.configure(text="Aguardando inserção do Cartão SD...", text_color="orange")
        for widget in self.frame_pastas.winfo_children():
            widget.destroy()
        self.checkboxes_pastas.clear()
        self.lbl_vazio = ctk.CTkLabel(self.frame_pastas, text="Nenhum cartão detectado.")
        self.lbl_vazio.pack(pady=40)

    def selecionar_destino(self):
        pasta = filedialog.askdirectory(title="Selecione onde salvar as fotos")
        if pasta:
            self.destino_path.set(pasta)
            self.combo_destino_var.set("Escolher pasta personalizada...")
        else:
            if not self.destino_path.get():
                self.combo_destino_var.set("Escolher pasta personalizada...")
            else:
                encontrou = False
                for p in self.pastas_local:
                    if p['caminho'] == self.destino_path.get():
                        self.combo_destino_var.set(p['nome'])
                        encontrou = True
                        break
                if not encontrou:
                    self.combo_destino_var.set("Escolher pasta personalizada...")

    def novo_descarregamento(self):
        # Limpa o nome do fotógrafo
        self.entry_nome.delete(0, 'end')
        
        # Reseta os arquivos transferidos
        self.arquivos_transferidos.clear()
        
        # Reseta o progresso
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")
        
        # Desabilita botões secundários
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.btn_iniciar.configure(state="normal")
        
        # Reseta a pasta do Computador para a primeira predefinida ou personalizada
        if self.pastas_local:
            self.combo_destino_var.set(self.pastas_local[0]['nome'])
            self.destino_path.set(self.pastas_local[0]['caminho'])
        else:
            self.combo_destino_var.set("Escolher pasta personalizada...")
            self.destino_path.set("")
            
        # Reseta e recarrega os cartões/pastas de origem
        if self.cartao_detectado and self.drive_path:
            self.atualizar_ui_cartao_detectado(self.drive_path, e_manual=self.origem_manual)
        else:
            self.atualizar_ui_cartao_removido()

    def iniciar_transferencia(self):
        if not self.cartao_detectado:
            messagebox.showwarning("Aviso", "Nenhum cartão SD detectado!")
            return
            
        nome_fotografo = self.entry_nome.get().strip()
        if not nome_fotografo:
            messagebox.showwarning("Aviso", "Por favor, digite o nome do fotógrafo!")
            return
            
        destino = self.destino_path.get()
        if not destino:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino no computador!")
            return

        pastas_selecionadas = [var.get() for var in self.checkboxes_pastas if var.get() != ""]
        if not pastas_selecionadas:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma pasta do cartão para descarregar!")
            return

        self.btn_iniciar.configure(state="disabled")
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.combo_destino.configure(state="disabled")
        self.btn_destino.configure(state="disabled")
        
        criar_pasta_fotografo = self.criar_pasta_fotografo_var.get()
        
        # Limpa os arquivos transferidos antes de uma nova importação
        self.arquivos_transferidos.clear()
        
        thread_copia = threading.Thread(
            target=self.processar_copia, 
            args=(nome_fotografo, destino, pastas_selecionadas, criar_pasta_fotografo)
        )
        thread_copia.start()

    def processar_copia(self, nome_fotografo, destino, pastas_selecionadas, criar_pasta_fotografo):
        if criar_pasta_fotografo:
            destino = os.path.join(destino, nome_fotografo)
            
        os.makedirs(destino, exist_ok=True)
        arquivos_para_copiar = []
        
        for pasta_relativa in pastas_selecionadas:
            pasta_origem = os.path.join(self.drive_path, os.path.normpath(pasta_relativa))
            if os.path.exists(pasta_origem):
                for root, dirs, files in os.walk(pasta_origem):
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                            arquivos_para_copiar.append(os.path.join(root, file))

        total_arquivos = len(arquivos_para_copiar)
        if total_arquivos == 0:
            self.after(0, lambda: messagebox.showinfo("Informação", "Nenhuma imagem encontrada nas pastas selecionadas."))
            self.after(0, lambda: self.btn_iniciar.configure(state="normal"))
            return

        # Verifica se há fotos em formato RAW nas pastas selecionadas
        tem_raw = any(f.lower().endswith(('.cr2', '.nef', '.arw', '.cr3')) for f in arquivos_para_copiar)
        if tem_raw:
            confirmar = [True]
            event = threading.Event()
            
            def exibir_aviso():
                res = messagebox.askyesno(
                    "Fotos em RAW Detectadas",
                    "Atenção: Foram detectadas fotos em formato RAW (.cr3, .cr2, .nef, .arw) nas pastas selecionadas.\n\n"
                    "Elas serão copiadas no formato original. Deseja prosseguir com o descarregamento?"
                )
                confirmar[0] = res
                event.set()
                
            self.after(0, exibir_aviso)
            event.wait()
            
            if not confirmar[0]:
                def reativar_controles():
                    self.btn_iniciar.configure(state="normal")
                    self.combo_destino.configure(state="normal")
                    self.btn_destino.configure(state="normal")
                    if self.arquivos_transferidos:
                        self.btn_selecionar.configure(state="normal")
                        self.btn_abrir.configure(state="normal")
                self.after(0, reativar_controles)
                return

        # Ordena os arquivos por data de modificação para garantir ordem cronológica na renomeação sequencial
        try:
            arquivos_para_copiar.sort(key=lambda x: os.path.getmtime(x))
        except Exception:
            arquivos_para_copiar.sort()

        # Determina o formato dos dígitos baseado no total de arquivos a transferir (mínimo de 3 dígitos)
        digitos = max(3, len(str(total_arquivos)))

        # Encontra o próximo número sequencial disponível no destino para este fotógrafo
        contador_inicio = 1
        try:
            arquivos_destino = os.listdir(destino)
            prefixo = f"{nome_fotografo}_"
            numeros_existentes = []
            for f in arquivos_destino:
                if f.startswith(prefixo):
                    parte_sem_prefixo = f[len(prefixo):]
                    nome_sem_ext_dest, _ = os.path.splitext(parte_sem_prefixo)
                    parte_numerica = nome_sem_ext_dest.split('_')[0]
                    if parte_numerica.isdigit():
                        numeros_existentes.append(int(parte_numerica))
            if numeros_existentes:
                contador_inicio = max(numeros_existentes) + 1
        except Exception as e:
            print(f"Erro ao calcular offset de numeração: {e}")

        progresso_atual = 0
        lock = threading.Lock()

        def processar_arquivo(item):
            nonlocal progresso_atual
            idx, caminho_arquivo = item
            nome_original = os.path.basename(caminho_arquivo)
            _, ext = os.path.splitext(nome_original)
            
            ext_final = ext.lower()
            num_formatado = f"{idx + contador_inicio:0{digitos}d}"
            novo_nome = f"{nome_fotografo}_{num_formatado}{ext_final}"
            caminho_destino = os.path.join(destino, novo_nome)

            contador = 1
            while os.path.exists(caminho_destino):
                nome_base, ext_base = os.path.splitext(novo_nome)
                caminho_destino = os.path.join(destino, f"{nome_base}_{contador}{ext_base}")
                contador += 1

            try:    
                # Cópia direta do arquivo original (RAW, PNG, JPG, MP4, etc.)
                shutil.copy2(caminho_arquivo, caminho_destino)
                
                # Armazena os arquivos transferidos com sucesso de forma thread-safe
                with lock:
                    # Só adicionamos imagens legíveis (ignoramos vídeos no revisor se houver)
                    if caminho_destino.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3')):
                        self.arquivos_transferidos.append(caminho_destino)
            except Exception as e:
                print(f"Erro ao processar {nome_original}: {e}")
            
            with lock:
                progresso_atual += 1
                progresso = progresso_atual / total_arquivos
                percentual = int(progresso * 100)
                self.progressbar.set(progresso)
                self.lbl_progresso.configure(text=f"Progresso: {percentual}% ({progresso_atual}/{total_arquivos})")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(processar_arquivo, enumerate(arquivos_para_copiar))

        # Chama a finalização da transferência de forma segura na thread principal
        self.after(0, self.finalizar_transferencia_gui)

    def finalizar_transferencia_gui(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_abrir.configure(state="normal")
        self.combo_destino.configure(state="normal")
        self.btn_destino.configure(state="normal")
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")
        
        total_fotos = len(self.arquivos_transferidos)
        if total_fotos > 0:
            self.registrar_historico()
            self.btn_selecionar.configure(state="normal")
            
            # Pergunta se o usuário gostaria de abrir o painel de seleção diretamente
            revisar = messagebox.askyesno(
                "Transferência Finalizada",
                f"Foram transferidas {total_fotos} foto(s) com sucesso!\n\n"
                "Deseja iniciar a tela de seleção agora para revisar e apagar as fotos indesejadas?"
            )
            if revisar:
                self.abrir_revisor()
        else:
            messagebox.showinfo("Concluído", "A cópia foi finalizada, mas nenhuma imagem compatível com revisão foi transferida.")

    def abrir_revisor(self):
        if not self.arquivos_transferidos:
            messagebox.showwarning("Aviso", "Não há fotos na lista de transferência para revisar.")
            return
            
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        
        # Abre a tela de revisão
        self.janela_revisao = RevisorFotosWindow(self, self.arquivos_transferidos, self.destino_path.get())

    def abrir_pasta(self):
        destino = self.destino_path.get()
        nome_fotografo = self.entry_nome.get().strip()
        if nome_fotografo and self.criar_pasta_fotografo_var.get():
            destino_sub = os.path.join(destino, nome_fotografo)
            if os.path.exists(destino_sub):
                destino = destino_sub
                
        if destino and os.path.exists(destino):
            if platform.system() == "Windows":
                os.startfile(destino)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", destino])
            else:
                subprocess.Popen(["xdg-open", destino])



if __name__ == "__main__":
    app = ImportadorFotosApp()
    app.mainloop()