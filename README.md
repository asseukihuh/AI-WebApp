# Turn on your local ai-webapp ! 🤖

## Summary

<a href="#linux">Install on linux</a><br>
<a href="#windows">Install on windows</a>


### Minimal specs :
Operating System: Linux, Mac or Windows <br>
Memory (RAM): 8GB <br>
Processor: A relatively modern CPU (5 years, 4 cores) <br>
GPU: Integrated GPU works but runs slow <br>

### Recommended specs :
Operating System: Linux, Mac or Windows <br>
Memory (RAM): 16GB <br>
Processor: A relatively modern CPU (5 years, 8 cores) <br>
GPU: Dedicated GPU 6GB VRAM minimal (CUDA is the best) <br>

## Configuration :

### <p id="linux">Linux</p>

#### 1. Install ollama
   
```
curl -fsSL https://ollama.com/install.sh | sh
```
#### 2. Run ollama
   
```
ollama serve
```

#### 3. Choose a model and make sure it runs

You can find models at <a href='https://ollama.com/search'>ollama.com/search</a>.

Once you found your model run it and test some prompts to make sure it runs.

```
ollama run <model name>
```

#### 4. Clone this repository in your computer

```
git clone https://github.com/asseukihuh/ai-webapp
```

#### 5. Host a server in your computer

```
python -m http.server 8000
```

#### 6. Test your local ai-webapp

Go to the adress localhost:8000 on your navigator. <br>

Find the repository where index.html is located. <br>

And there is your local ai-webapp. <br>

### <p id="windows">Windows</p>

#### 1. Install ollama
   
```
curl -fsSL https://ollama.com/install.sh | sh
```
#### 2. Run ollama
   
```
ollama serve
```

#### 3. Choose a model and make sure it runs

You can find models at <a href='https://ollama.com/search'>ollama.com/search</a>.

Once you found your model run it and test some prompts to make sure it runs.

```
ollama run <model name>
```

#### 4. Clone this repository in your computer

```
git clone https://github.com/asseukihuh/ai-webapp
```

#### 5. Host a server in your computer

```
python -m http.server 8000
```

#### 6. Test your local ai-webapp

Go to the adress localhost:8000 on your navigator. <br>

Find the repository where index.html is located. <br>

And there is your local ai-webapp. <br>




